import os
import cv2
import pytesseract
import re
import hashlib
from preprocess_receipt import preprocess_receipt
from product_matcher import indentify_item
from save_list import *
from utils import *
from db import get_connection


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RECEIPT_FOLDER = os.path.join(BASE_DIR, "receipts")
DEBUG_OCR_FILE = os.path.join(BASE_DIR, "debug_ocr.txt")

# Garage Celeron: prefer finishing OCR over fake timeouts
MIN_GOOD_ITEMS = 3
OCR_WIDTH = 1200
FALLBACK_VARIANT_NAMES = {"Gray", "CLAHE", "Otsu"}

price_pattern = re.compile(
    r"(.+?)\s+\$?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2}))"
    r"[^\d]*$",
    re.IGNORECASE,
)
price_only_pattern = re.compile(
    r"^\$?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2}))\s*[A-Za-z]*\s*$"
)
date_pattern = re.compile(
    r"\b(?:"
    r"(?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])[-/.](?:\d{2}|\d{4})"
    r"|"
    r"(?:0?[1-9]|[12]\d|3[01])[-/.](?:0?[1-9]|1[0-2])[-/.](?:\d{2}|\d{4})"
    r")\b"
)

def normalize_ocr_line(line):
    line = (
        line.replace("|", " ")
        .replace("{", " ")
        .replace("}", " ")
        .replace("«", " ")
        .replace("»", " ")
        .replace("©", " ")
    )
    # "2. 89" / "3. 18" -> "2.89" / "3.18"
    line = re.sub(r"(\d)\.\s+(\d{2})", r"\1.\2", line)
    line = re.sub(r"\s+", " ", line).strip()
    return line


def count_item_matches(text):
    hits = 0
    lines = [
        normalize_ocr_line(ln)
        for ln in text.splitlines()
        if ln.strip()
    ]
    for i, line in enumerate(lines):
        if price_pattern.search(line):
            hits += 1
            continue
        if price_only_pattern.match(line) and i > 0:
            prev = lines[i - 1]
            if not price_pattern.search(prev) and not price_only_pattern.match(prev):
                if len(clean_item_name(prev)) >= 3 and not ignored(prev):
                    hits += 1
    return hits


def extract_items_from_lines(lines):
    items = []
    i = 0
    while i < len(lines):
        line = normalize_ocr_line(lines[i])
        match = price_pattern.search(line)

        if match:
            raw_name = match.group(1).strip()
            price_raw = match.group(2)
        elif price_only_pattern.match(line) and i > 0:
            raw_name = normalize_ocr_line(lines[i - 1])
            price_raw = price_only_pattern.match(line).group(1)
            if price_pattern.search(raw_name) or price_only_pattern.match(raw_name):
                i += 1
                continue
        else:
            i += 1
            continue

        if ignored(raw_name):
            i += 1
            continue

        # Skip weight / multipack unit-price lines
        upper_raw = raw_name.upper()
        if re.search(
            r"(\d+\s*@|/ ?I[BL]|/ ?LB|\bI[BL]\b|\bLB\b|\bEACH\b|\bSAVINGS\b)",
            upper_raw,
        ):
            i += 1
            continue

        try:
            price = float(normalize_price(price_raw))
        except (ValueError, TypeError):
            i += 1
            continue

        # Skip obvious OCR garbage prices
        if price <= 0 or price > 50:
            i += 1
            continue

        clean = clean_item_name(raw_name)

        # Too short / mostly digits (e.g. "2 0", barcodes-only)
        if len(clean) < 4:
            i += 1
            continue
        if len(re.sub(r"\d", "", clean)) < 3:
            i += 1
            continue

        items.append((raw_name, clean, price))
        i += 1

    return items

def get_file_hash(filepath):
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


def already_processed(cur, filepath):
    file_hash = get_file_hash(filepath)
    cur.execute(
        "SELECT id FROM processed_files WHERE file_hash = ?",
        (file_hash,),
    )
    return cur.fetchone() is not None


def mark_processed(cur, filename, filepath):
    file_hash = get_file_hash(filepath)
    cur.execute(
        """
        INSERT OR IGNORE INTO processed_files
        (filename, file_hash)
        VALUES (?, ?)
        """,
        (filename, file_hash),
    )


def resize_for_ocr(img, target_width=OCR_WIDTH):
    """Keep OCR images small enough for the Celeron."""
    h, w = img.shape[:2]
    if w == target_width:
        return img
    scale = target_width / float(w)
    interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(img, None, fx=scale, fy=scale, interpolation=interp)

def prepare_simple_image(image):
    """Light gray image — similar to the old single-file approach."""
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    gray = resize_for_ocr(gray)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def run_ocr(img, psm):
    ocr_img = resize_for_ocr(img)
    text = pytesseract.image_to_string(
        ocr_img,
        config=f"--oem 3 --psm {psm}",
    )
    return (
        text.replace("$ ", "$")
        .replace(" ,", ",")
        .replace(" .", ".")
    )


def ocr_attempt(img_name, img, psm):
    print(f"Method: {img_name} | PSM mode: {psm}", flush=True)
    try:
        text = run_ocr(img, psm)
        items = count_item_matches(text)
        score = score_ocr(text)
    except Exception as e:
        print(f"[Error skipped] {img_name} failed on PSM {psm}: {e}")
        text, items, score = "", 0, -100

    print(
        f" OCR result: {img_name} PSM:{psm} "
        f"chars:{len(text)} items:{items} score:{score}"
    )
    return (items, score, text, img_name, psm)

def process_receipts():
    print("\nProcessing newly uploaded receipts.")
    print("\nPlease wait...")

    try:
        pytesseract.get_tesseract_version()
    except Exception:
        print("Tesseract OCR is not installed or configured.")
        return

    conn = get_connection()
    cur = conn.cursor()

    for filename in sorted(os.listdir(RECEIPT_FOLDER)):
        if not filename.lower().endswith((".png", ".jpg", ".jpeg")):
            continue

        path = os.path.join(RECEIPT_FOLDER, filename)
        if already_processed(cur, path):
            print(f"Skipping {filename} (already processed)")
            continue

        print("\n======================")
        print("Processing", filename)
        print("======================")

        image = cv2.imread(path)
        if image is None:
            continue

        results = []

        # 1) Simple path
        simple = prepare_simple_image(image)
        result = ocr_attempt("Simple", simple, 4)
        results.append(result)

        # 2) Fallback only if needed
        if result[0] < MIN_GOOD_ITEMS:
            print(
                f"\nSimple OCR found {result[0]} items; "
                "running limited fallback..."
            )
            variants = preprocess_receipt(image, debug=False)
            variants = [
                (name, img)
                for name, img in variants
                if name in FALLBACK_VARIANT_NAMES
            ]

            stop_fallback = False
            for img_name, img in variants:
                for psm in (4, 6):
                    result = ocr_attempt(img_name, img, psm)
                    results.append(result)
                    if result[0] >= MIN_GOOD_ITEMS:
                        print(
                            f"\nGood item count ({result[0]}) reached; "
                            "stopping fallback early."
                        )
                        stop_fallback = True
                        break
                if stop_fallback:
                    break

        if not results:
            print("No OCR results produced.")
            continue

        best_items, best_score, best_text, best_method, best_psm = max(
            results,
            key=lambda x: (x[0], x[1]),
        )

        print(f"\nSelected preprocessing: {best_method}")
        print(f"Selected PSM: {best_psm}")
        print(f"Selected item matches: {best_items}")
        print(f"Selected OCR score: {best_score}")

        if len(best_text.strip()) < 10:
            print("Poor OCR result, skipping.")
            continue

        lines = [
                normalize_ocr_line(line)
                for line in best_text.splitlines()
                    if line.strip()
            ]

        with open(DEBUG_OCR_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n\n--- {filename} ---\n")
            f.write(
                f"Method: {best_method}, PSM: {best_psm}, "
                f"items:{best_items}, score:{best_score}\n\n"
            )
            for line in lines:
                f.write(line + "\n")

        # store
        store = "Unknown"
        found = False
        for line in lines[:15]:
            c = clean_item_name(line)
            for key, val in STORE_NAMES.items():
                if key in c:
                    store = val
                    found = True
                    break
            if found:
                break

        # date
        receipt_date = ""
        for line in lines:
            m = date_pattern.search(line)
            if m:
                receipt_date = m.group()
                break
        print(f"Date: {receipt_date}")

        # address
        address = ""
        city_state = ""
        full_address = ""

        address_pattern = re.compile(
            r"^\d{1,6}\s+.+(?:,\s*[A-Z .\'-]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?)?$",
            re.IGNORECASE,
        )
        city_pattern = re.compile(
            r"^[A-Z .\'-]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?$",
            re.IGNORECASE,
        )

        for i, line in enumerate(lines[:20]):
            if address_pattern.match(line):
                if any(
                    x in line.upper()
                    for x in ("ST#", "OP#", "TR", "TEL", "PHONE")
                ):
                    continue
                address = line
                if i + 1 < len(lines):
                    possible_city = lines[i + 1]
                    if city_pattern.match(possible_city):
                        city_state = possible_city
                break

        if address:
            full_address = address
        if city_state:
            full_address += ", " + city_state
        print(f"Address: {full_address}")

        parsed = extract_items_from_lines(lines)
        #lines 367-399 sku/upc handling
        for raw_name, clean, price in parsed:
        
            match = identify_item(
                cur,
                raw_name,
                clean,
                price,
            )
        
            print(
                f"{clean} -> ${price:.2f} | "
                f"ID: {match['identifier']} | "
                f"Match: {match['canonical_name']} | "
                f"Confidence: {match['confidence']}"
            )
        
            items.append((clean, price))
        
            cur.execute(
                """
                INSERT OR IGNORE INTO items
                (store, full_address, date, raw_name, clean_name, price)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    store,
                    full_address,
                    receipt_date,
                    raw_name,
                    clean,
                    price,
                ),
            )
        
        items = []
        for raw_name, clean, price in parsed:
            items.append((clean, price))
            cur.execute(
                """
                INSERT OR IGNORE INTO items
                (store, full_address, date, raw_name, clean_name, price)
                VALUES (?,?,?,?,?,?)
                """,
                (store, full_address, receipt_date, raw_name, clean, price),
            )
            print(f"{clean} -> ${price:.2f}")

        append_list(store, receipt_date, full_address, items)
        mark_processed(cur, filename, path)
        conn.commit()

    conn.close()
    print("\nFinished, receipt info updated.")


if __name__ == "__main__":
    process_receipts()

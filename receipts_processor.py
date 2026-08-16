# receipts_processor.py

import os
import cv2
import pytesseract
import re
import hashlib

from preprocess_receipt import preprocess_receipt
from save_list import append_list
from utils import (
    clean_item_name,
    ignored,
    normalize_price,
    score_ocr,
    STORE_NAMES,
)
from db import get_connection


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

RECEIPT_FOLDER = os.path.join(
    BASE_DIR,
    "receipts",
)

DEBUG_OCR_FILE = os.path.join(
    BASE_DIR,
    "debug_ocr.txt",
)


# ---------------------------------------------------------------------------
# OCR settings
# ---------------------------------------------------------------------------

MIN_GOOD_ITEMS = 3

OCR_WIDTH = 1200

FALLBACK_VARIANT_NAMES = {
    "Gray",
    "CLAHE",
    "Otsu",
}


# ---------------------------------------------------------------------------
# Receipt parsing patterns
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# OCR line normalization
# ---------------------------------------------------------------------------

def normalize_ocr_line(line):
    """
    Clean obvious OCR formatting artifacts.
    """

    line = (
        line
        .replace("|", " ")
        .replace("{", " ")
        .replace("}", " ")
        .replace("«", " ")
        .replace("»", " ")
        .replace("©", " ")
    )

    line = re.sub(
        r"(\d)\.\s+(\d{2})",
        r"\1.\2",
        line,
    )

    line = re.sub(
        r"\s+",
        " ",
        line,
    ).strip()

    return line


# ---------------------------------------------------------------------------
# OCR item counting
# ---------------------------------------------------------------------------

def count_item_matches(text):
    """
    Estimate how many receipt items OCR found.
    """

    hits = 0

    lines = [
        normalize_ocr_line(line)
        for line in text.splitlines()
        if line.strip()
    ]

    for i, line in enumerate(lines):

        if price_pattern.search(line):
            hits += 1
            continue

        if (
            price_only_pattern.match(line)
            and i > 0
        ):

            prev = lines[i - 1]

            if (
                not price_pattern.search(prev)
                and not price_only_pattern.match(prev)
            ):

                if (
                    len(clean_item_name(prev)) >= 3
                    and not ignored(prev)
                ):
                    hits += 1

    return hits


# ---------------------------------------------------------------------------
# Item extraction
# ---------------------------------------------------------------------------

def extract_items_from_lines(lines):
    """
    Extract receipt item names and prices.

    Returns:

        [
            (raw_name, clean_name, price),
            ...
        ]
    """

    items = []

    i = 0

    while i < len(lines):

        line = normalize_ocr_line(lines[i])

        match = price_pattern.search(line)

        # ---------------------------------------------------------------
        # Item and price on same line
        # ---------------------------------------------------------------

        if match:

            raw_name = match.group(1).strip()
            price_raw = match.group(2)

        # ---------------------------------------------------------------
        # Item on previous line, price on current line
        # ---------------------------------------------------------------

        elif (
            price_only_pattern.match(line)
            and i > 0
        ):

            raw_name = normalize_ocr_line(
                lines[i - 1]
            )

            price_raw = price_only_pattern.match(
                line
            ).group(1)

            if (
                price_pattern.search(raw_name)
                or price_only_pattern.match(raw_name)
            ):
                i += 1
                continue

        else:

            i += 1
            continue

        # ---------------------------------------------------------------
        # Ignore known non-item lines
        # ---------------------------------------------------------------

        if ignored(raw_name):

            i += 1
            continue

        # ---------------------------------------------------------------
        # Skip weight / multipack / savings lines
        # ---------------------------------------------------------------

        upper_raw = raw_name.upper()

        if re.search(
            r"(\d+\s*@|/ ?I[BL]|/ ?LB|\bI[BL]\b|\bLB\b|\bEACH\b|\bSAVINGS\b)",
            upper_raw,
        ):

            i += 1
            continue

        # ---------------------------------------------------------------
        # Normalize price
        # ---------------------------------------------------------------

        try:

            price = float(
                normalize_price(price_raw)
            )

        except (
            ValueError,
            TypeError,
        ):

            i += 1
            continue

        # ---------------------------------------------------------------
        # Skip obvious OCR garbage prices
        # ---------------------------------------------------------------

        if price <= 0 or price > 50:

            i += 1
            continue

        # ---------------------------------------------------------------
        # Clean item name
        # ---------------------------------------------------------------

        clean = clean_item_name(
            raw_name
        )

        if len(clean) < 4:

            i += 1
            continue

        if len(
            re.sub(r"\d", "", clean)
        ) < 3:

            i += 1
            continue

        items.append(
            (
                raw_name,
                clean,
                price,
            )
        )

        i += 1

    return items


# ---------------------------------------------------------------------------
# File hashing
# ---------------------------------------------------------------------------

def get_file_hash(filepath):

    hasher = hashlib.sha256()

    with open(
        filepath,
        "rb",
    ) as f:

        while chunk := f.read(8192):

            hasher.update(chunk)

    return hasher.hexdigest()


def already_processed(cur, filepath):

    file_hash = get_file_hash(
        filepath
    )

    cur.execute(
        """
        SELECT id
        FROM processed_files
        WHERE file_hash = ?
        """,
        (file_hash,),
    )

    return cur.fetchone() is not None


def mark_processed(
    cur,
    filename,
    filepath,
):

    file_hash = get_file_hash(
        filepath
    )

    cur.execute(
        """
        INSERT OR IGNORE INTO processed_files
        (filename, file_hash)
        VALUES (?, ?)
        """,
        (
            filename,
            file_hash,
        ),
    )


# ---------------------------------------------------------------------------
# Receipt record
# ---------------------------------------------------------------------------

def create_receipt(
    cur,
    filename,
    filepath,
    store,
    full_address,
    receipt_date,
):
    """
    Create the master receipt record.

    Returns the receipt ID.

    This is the parent record for all items found on this receipt.
    """

    file_hash = get_file_hash(
        filepath
    )

    cur.execute(
        """
        INSERT OR IGNORE INTO receipts
        (
            filename,
            file_hash,
            store,
            full_address,
            date
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            filename,
            file_hash,
            store,
            full_address,
            receipt_date,
        ),
    )

    # Retrieve the receipt ID whether the row was newly inserted
    # or already existed.

    cur.execute(
        """
        SELECT id
        FROM receipts
        WHERE file_hash = ?
        """,
        (file_hash,),
    )

    result = cur.fetchone()

    if not result:

        raise RuntimeError(
            f"Could not create receipt record "
            f"for {filename}"
        )

    return result[0]


# ---------------------------------------------------------------------------
# Image preparation
# ---------------------------------------------------------------------------

def resize_for_ocr(
    img,
    target_width=OCR_WIDTH,
):

    h, w = img.shape[:2]

    if w == target_width:
        return img

    scale = (
        target_width
        / float(w)
    )

    interp = (
        cv2.INTER_AREA
        if scale < 1.0
        else cv2.INTER_CUBIC
    )

    return cv2.resize(
        img,
        None,
        fx=scale,
        fy=scale,
        interpolation=interp,
    )


def prepare_simple_image(image):

    if len(image.shape) == 3:

        gray = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2GRAY,
        )

    else:

        gray = image.copy()

    gray = resize_for_ocr(
        gray
    )

    clahe = cv2.createCLAHE(
        clipLimit=2.0,
        tileGridSize=(8, 8),
    )

    return clahe.apply(
        gray
    )


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def run_ocr(
    img,
    psm,
):

    ocr_img = resize_for_ocr(
        img
    )

    text = pytesseract.image_to_string(
        ocr_img,
        config=f"--oem 3 --psm {psm}",
    )

    return (
        text
        .replace("$ ", "$")
        .replace(" ,", ",")
        .replace(" .", ".")
    )


def ocr_attempt(
    img_name,
    img,
    psm,
):

    print(
        f"Method: {img_name} | "
        f"PSM mode: {psm}",
        flush=True,
    )

    try:

        text = run_ocr(
            img,
            psm,
        )

        items = count_item_matches(
            text
        )

        score = score_ocr(
            text
        )

    except Exception as e:

        print(
            f"[Error skipped] "
            f"{img_name} failed on PSM {psm}: {e}"
        )

        text = ""
        items = 0
        score = -100

    print(
        f" OCR result: {img_name} "
        f"PSM:{psm} "
        f"chars:{len(text)} "
        f"items:{items} "
        f"score:{score}"
    )

    return (
        items,
        score,
        text,
        img_name,
        psm,
    )


# ---------------------------------------------------------------------------
# Store detection
# ---------------------------------------------------------------------------

def detect_store(lines):

    for line in lines[:15]:

        cleaned = clean_item_name(
            line
        )

        for key, value in STORE_NAMES.items():

            if key in cleaned:

                return value

    return "Unknown"


# ---------------------------------------------------------------------------
# Date detection
# ---------------------------------------------------------------------------

def detect_receipt_date(lines):

    for line in lines:

        match = date_pattern.search(
            line
        )

        if match:

            return match.group()

    return ""


# ---------------------------------------------------------------------------
# Address detection
# ---------------------------------------------------------------------------

def detect_address(lines):

    address = ""
    city_state = ""

    address_pattern = re.compile(
        r"^\d{1,6}\s+.+(?:,\s*[A-Z .\'-]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?)?$",
        re.IGNORECASE,
    )

    city_pattern = re.compile(
        r"^[A-Z .\'-]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?$",
        re.IGNORECASE,
    )

    for i, line in enumerate(
        lines[:20]
    ):

        if not address_pattern.match(
            line
        ):
            continue

        if any(
            x in line.upper()
            for x in (
                "ST#",
                "OP#",
                "TR",
                "TEL",
                "PHONE",
            )
        ):
            continue

        address = line

        if i + 1 < len(lines):

            possible_city = lines[
                i + 1
            ]

            if city_pattern.match(
                possible_city
            ):
                city_state = possible_city

        break

    full_address = ""

    if address:
        full_address = address

    if city_state:

        if full_address:
            full_address += ", "

        full_address += city_state

    return full_address


# ---------------------------------------------------------------------------
# Debug OCR
# ---------------------------------------------------------------------------

def save_debug_ocr(
    filename,
    method,
    psm,
    item_count,
    score,
    lines,
):

    with open(
        DEBUG_OCR_FILE,
        "a",
        encoding="utf-8",
    ) as f:

        f.write(
            f"\n\n--- {filename} ---\n"
        )

        f.write(
            f"Method: {method}, "
            f"PSM: {psm}, "
            f"items:{item_count}, "
            f"score:{score}\n\n"
        )

        for line in lines:

            f.write(
                line + "\n"
            )


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process_receipts():

    print(
        "\nProcessing newly uploaded receipts."
    )

    print(
        "\nPlease wait..."
    )

    # -----------------------------------------------------------------------
    # Verify Tesseract
    # -----------------------------------------------------------------------

    try:

        pytesseract.get_tesseract_version()

    except Exception:

        print(
            "Tesseract OCR is not installed "
            "or configured."
        )

        return

    # -----------------------------------------------------------------------
    # Database
    # -----------------------------------------------------------------------

    conn = get_connection()
    cur = conn.cursor()

    # -----------------------------------------------------------------------
    # Receipt files
    # -----------------------------------------------------------------------

    for filename in sorted(
        os.listdir(RECEIPT_FOLDER)
    ):

        if not filename.lower().endswith(
            (
                ".png",
                ".jpg",
                ".jpeg",
            )
        ):
            continue

        path = os.path.join(
            RECEIPT_FOLDER,
            filename,
        )

        # ---------------------------------------------------------------
        # Already processed?
        # ---------------------------------------------------------------

        if already_processed(
            cur,
            path,
        ):

            print(
                f"Skipping {filename} "
                f"(already processed)"
            )

            continue

        print(
            "\n======================"
        )

        print(
            "Processing",
            filename,
        )

        print(
            "======================"
        )

        # ---------------------------------------------------------------
        # Load image
        # ---------------------------------------------------------------

        image = cv2.imread(
            path
        )

        if image is None:

            print(
                f"Could not read {filename}"
            )

            continue

        results = []

        # ---------------------------------------------------------------
        # Simple OCR
        # ---------------------------------------------------------------

        simple = prepare_simple_image(
            image
        )

        result = ocr_attempt(
            "Simple",
            simple,
            4,
        )

        results.append(
            result
        )

        # ---------------------------------------------------------------
        # Fallback OCR
        # ---------------------------------------------------------------

        if result[0] < MIN_GOOD_ITEMS:

            print(
                f"\nSimple OCR found "
                f"{result[0]} items; "
                f"running limited fallback..."
            )

            variants = preprocess_receipt(
                image,
                debug=False,
            )

            variants = [
                (name, img)
                for name, img in variants
                if name in FALLBACK_VARIANT_NAMES
            ]

            stop_fallback = False

            for img_name, img in variants:

                for psm in (
                    4,
                    6,
                ):

                    result = ocr_attempt(
                        img_name,
                        img,
                        psm,
                    )

                    results.append(
                        result
                    )

                    if result[0] >= MIN_GOOD_ITEMS:

                        print(
                            f"\nGood item count "
                            f"({result[0]}) reached; "
                            f"stopping fallback early."
                        )

                        stop_fallback = True
                        break

                if stop_fallback:
                    break

        # ---------------------------------------------------------------
        # Select OCR result
        # ---------------------------------------------------------------

        if not results:

            print(
                "No OCR results produced."
            )

            continue

        (
            best_items,
            best_score,
            best_text,
            best_method,
            best_psm,
        ) = max(
            results,
            key=lambda x: (
                x[0],
                x[1],
            ),
        )

        print(
            f"\nSelected preprocessing: "
            f"{best_method}"
        )

        print(
            f"Selected PSM: "
            f"{best_psm}"
        )

        print(
            f"Selected item matches: "
            f"{best_items}"
        )

        print(
            f"Selected OCR score: "
            f"{best_score}"
        )

        # ---------------------------------------------------------------
        # Reject empty OCR
        # ---------------------------------------------------------------

        if len(
            best_text.strip()
        ) < 10:

            print(
                "Poor OCR result, skipping."
            )

            continue

        # ---------------------------------------------------------------
        # Normalize OCR lines
        # ---------------------------------------------------------------

        lines = [
            normalize_ocr_line(line)
            for line in best_text.splitlines()
            if line.strip()
        ]

        # ---------------------------------------------------------------
        # Save debug OCR
        # ---------------------------------------------------------------

        save_debug_ocr(
            filename=filename,
            method=best_method,
            psm=best_psm,
            item_count=best_items,
            score=best_score,
            lines=lines,
        )

        # ---------------------------------------------------------------
        # Receipt metadata
        # ---------------------------------------------------------------

        store = detect_store(
            lines
        )

        receipt_date = detect_receipt_date(
            lines
        )

        full_address = detect_address(
            lines
        )

        print(
            f"Store: {store}"
        )

        print(
            f"Date: {receipt_date}"
        )

        print(
            f"Address: {full_address}"
        )

        # ---------------------------------------------------------------
        # Extract items
        # ---------------------------------------------------------------

        parsed = extract_items_from_lines(
            lines
        )

        print(
            f"Parsed {len(parsed)} receipt items."
        )

        # ---------------------------------------------------------------
        # Create receipt record
        # ---------------------------------------------------------------

        try:

            receipt_id = create_receipt(
                cur=cur,
                filename=filename,
                filepath=path,
                store=store,
                full_address=full_address,
                receipt_date=receipt_date,
            )

        except Exception as e:

            print(
                f"Could not create receipt record: {e}"
            )

            conn.rollback()
            continue

        print(
            f"Receipt ID: {receipt_id}"
        )

        # ---------------------------------------------------------------
        # Store items
        # ---------------------------------------------------------------

        items = []

        for line_number, (
            raw_name,
            clean,
            price,
        ) in enumerate(
            parsed,
            start=1,
        ):

            items.append(
                (
                    clean,
                    price,
                )
            )

            cur.execute(
                """
                INSERT INTO items
                (
                    receipt_id,
                    line_number,
                    store,
                    full_address,
                    date,
                    raw_name,
                    clean_name,
                    price
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    line_number,
                    store,
                    full_address,
                    receipt_date,
                    raw_name,
                    clean,
                    price,
                ),
            )

            print(
                f"{line_number:02d}. "
                f"{clean} -> ${price:.2f}"
            )

        # ---------------------------------------------------------------
        # Human-readable list
        # ---------------------------------------------------------------

        append_list(
            store,
            receipt_date,
            full_address,
            items,
        )

        # ---------------------------------------------------------------
        # Mark processed
        # ---------------------------------------------------------------

        mark_processed(
            cur,
            filename,
            path,
        )

        # ---------------------------------------------------------------
        # Commit this receipt
        # ---------------------------------------------------------------

        conn.commit()

    # -----------------------------------------------------------------------
    # Close database
    # -----------------------------------------------------------------------

    conn.close()

    print(
        "\nFinished, receipt info updated."
    )


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    process_receipts()

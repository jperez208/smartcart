import os
import cv2
import pytesseract
import re
import hashlib
import numpy as np
from preprocess_receipt import preprocess_receipt
from save_list import *
from utils import *
from db import get_connection
from concurrent.futures import ThreadPoolExecutor, TimeoutError



RECEIPT_FOLDER = "receipts"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

RECEIPT_FOLDER = os.path.join(BASE_DIR, "receipts")
DEBUG_OCR_FILE = os.path.join(BASE_DIR, "debug_ocr.txt")

price_pattern = re.compile(r"(.+?)\s+\$?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2}))", re.IGNORECASE)
date_pattern = re.compile(r'\b\d{1,2}[\s\-/.]+\d{1,2}[\s\-/.]+\d{2,4}\b', re.IGNORECASE)

def get_file_hash(filepath):
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


def already_processed(cur, filepath):
    file_hash = get_file_hash(filepath)

    cur.execute("""
    SELECT id FROM processed_files
    WHERE file_hash = ?
    """, (file_hash,))

    return cur.fetchone() is not None


def mark_processed(cur, filename, filepath):
    file_hash = get_file_hash(filepath)

    cur.execute("""
    INSERT OR IGNORE INTO processed_files
    (filename, file_hash)
    VALUES (?,?)
    """, (filename, file_hash))

def process_receipts():
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        print("Tesseract OCR is not installed or configured.")
        return

    conn = get_connection()
    cur = conn.cursor()
    TIMEOUT_LIMIT = 20.0

    # Share one thread pool across all items to reduce execution overhead
    with ThreadPoolExecutor(max_workers=1) as executor:
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

            #Change Following to debug=False after testing
            variants = preprocess_receipt(
                image,
                debug=True
            )
                
            #
            # ----------------------------
            # OCR selection
            # ----------------------------
            results = []
            GOOD_SCORE = 60
            found_good = False

            for img_name, img in variants:
                for psm in [4,11]:

                    print(f"\rMethod: {img_name} | PSM mode: {psm} ", end="", flush=True)

                    ocr_img = img

                    if ocr_img.shape[1] > 1800:
                        ocr_img = cv2.resize(
                            ocr_img,
                            None,
                            fx=0.75,
                            fy=0.75,
                            interpolation=cv2.INTER_AREA
                        )

                    future = executor.submit(
                        pytesseract.image_to_string,
                        ocr_img,
                        config=f"--oem 3 --psm {psm}"
                    )

                    try:
                        text = future.result(timeout=TIMEOUT_LIMIT)
                        text = text.replace("$ ", "$").replace(" ,", ",").replace(" .", ".")
                        score = score_ocr(text)

                    except TimeoutError:
                        print(f"\n[Timeout skipped] {img_name} hung on PSM {psm}")
                        text, score = "", -1

                    except Exception as e:
                        print(f"\n[Error skipped] {img_name} failed on PSM {psm}: {e}")
                        text, score = "", -1


                    print(
                        "OCR result:",
                        img_name,
                        "PSM:",
                        psm,
                        "chars:",
                        len(text),
                        "score:",
                        score
                    )

                    results.append(
                        (score, text, img, img_name, psm)
                    )


                    if score >= GOOD_SCORE:
                        print(
                            f"\nGood OCR score ({score}) reached. Skipping remaining OCR attempts."
                        )
                        found_good = True
                        break

                if found_good:
                    break


            # ============================
            # PICK BEST OCR RESULT
            # ============================

            if not results:
                print("No OCR results produced.")
                continue


            best_score, best_text, processed_img, best_method, best_psm = max(
                results,
                key=lambda x: x[0]
            )


            print(f"\nSelected preprocessing: {best_method}")
            print(f"Selected PSM: {best_psm}")
            print(f"Selected OCR score: {best_score}")


            if len(best_text.strip()) < 10:
                print("Poor OCR result, skipping.")
                continue
            lines = [
                line.strip()
                for line in best_text.splitlines()
                if line.strip()
            ]

            # print("OCR lines:", len(lines))
            with open(DEBUG_OCR_FILE, "a", encoding="utf-8") as f:
                f.write(f"\n\n--- {filename} ---\n")
                f.write(f"Method: {best_method}, PSM: {best_psm}\n\n")
                for line in lines:
                    f.write(line + "\n")
            
            # detect store
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
                append_list()
        
            # detect date
            receipt_date = ""
            for line in lines:
                m = date_pattern.search(line)
                if m:
                    receipt_date = m.group()
                    break
            print(f"Date: {receipt_date}")
        
            # ----------------------------
            # Store Address Detection
            # ----------------------------
            address = ""
            city_state = ""
            full_address = ""

            address_pattern = re.compile(r'^\d{1,6}\s+[A-Z0-9 .#-]+$', re.IGNORECASE)
            city_pattern = re.compile(r'^[A-Z .\'-]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?$', re.IGNORECASE)

            for i, line in enumerate(lines[:20]):
                if address_pattern.match(line):
                    if any(x in line.upper() for x in ["ST#", "OP#", "TR", "TEL", "PHONE"]):
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
    
            # items
            for line in lines:
                match = price_pattern.search(line)
                if not match:
                    continue

                raw_name = match.group(1).strip()
                price = normalize_price(match.group(2))

                if ignored(raw_name):
                    continue

                try:
                    price = float(price)
                except:
                    continue
    
                clean = clean_item_name(raw_name)

                if len(clean) < 3:
                    continue

                cur.execute("""
                INSERT OR IGNORE INTO items
                (store, full_address, date, raw_name, clean_name, price)
                VALUES (?,?,?,?,?,?)
                """, (store, full_address, receipt_date, raw_name, clean, price))

                print(f"{clean} -> ${price:.2f}")

            mark_processed(cur, filename, path)
            conn.commit()

        conn.close()

        print("\nFinished, receipt info updated.")
print("\nProcessing newly uploaded receipts.")
print("\nPlease wait...")

if __name__ == "__main__":
    process_receipts()

import os
import cv2
import pytesseract
import re
import hashlib
from utils import *
from db import get_connection


RECEIPT_FOLDER = "receipts"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

RECEIPT_FOLDER = os.path.join(BASE_DIR, "receipts")
DEBUG_OCR_FILE = "debug_ocr.txt"

price_pattern = re.compile(r"(.+?)\s+\$?\s*(\d+[.,]\d{2})", re.IGNORECASE)
date_pattern = re.compile(r'\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b', re.IGNORECASE)

def get_file_hash(filepath):
    with open(filepath, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


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
    conn = get_connection()
    cur = conn.cursor()

    for filename in os.listdir(RECEIPT_FOLDER):

        if not filename.lower().endswith((".png",".jpg",".jpeg")):
            continue

        path = os.path.join(RECEIPT_FOLDER, filename)

        if already_processed(cur, path):
            print(f"Skipping {filename} (already processed)")
            continue

        print("\n======================")
        print("Processing", filename)
        print("======================")

       # path = os.path.join(RECEIPT_FOLDER, filename)
        image = cv2.imread(path)

        if image is None:
            continue

        # preprocess
    #Old image processor
       # gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
       # gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
       # gray = cv2.fastNlMeansDenoising(gray)
       # gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
       # preprocess
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        gray = cv2.fastNlMeansDenoising(gray)
        
        # FIXED: Replaced Otsu with Adaptive Thresholding to prevent blacked-out text
        gray = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
        
        # OCR multi-psm
        results = []
        for psm in:
            # The whitelist configuration belongs INSIDE the loop so it can use the current psm variable
            custom_config = f"--psm {psm} -c tessedit_char_whitelist=abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.$,-/#% "
            text = pytesseract.image_to_string(gray, config=custom_config)
            results.append((score_ocr(text), text))
            print(f"\rPSM mode: {psm}", end="", flush=True)
            
        _, best_text = max(results, key=lambda x: x)

        # Write to your debug file to inspect the raw OCR output
        with open(DEBUG_OCR_FILE, "a", encoding="utf-8") as df:
            df.write(f"\n--- FILE: {filename} ---\n{best_text}\n")
            
        lines = [x.strip() for x in best_text.splitlines() if x.strip()]
        
        # detect store
        store = "Unknown"
        for line in lines[:15]:
            c = clean_item_name(line)
            for key,val in STORE_NAMES.items():
                if key in c:
                    store = val
                    break
        print(f"\nStore: {store}")
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

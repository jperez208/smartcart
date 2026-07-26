import os
import cv2
import pytesseract
import re
from utils import *
from db import get_connection

#RECEIPT_FOLDER = "receipts"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

RECEIPT_FOLDER = os.path.join(BASE_DIR, "receipts")
DEBUG_OCR_FILE = "debug_ocr.txt"

price_pattern = re.compile(r"(.+?)\s+\$?\s*(\d+[.,]\d{2})", re.IGNORECASE)
date_pattern = re.compile(r'\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b', re.IGNORECASE)

def process_receipts():
    conn = get_connection()
    cur = conn.cursor()

    for filename in os.listdir(RECEIPT_FOLDER):

        if not filename.lower().endswith((".png",".jpg",".jpeg")):
            continue

        print("\n======================")
        print("Processing", filename)
        print("======================")

        path = os.path.join(RECEIPT_FOLDER, filename)
        image = cv2.imread(path)

        if image is None:
            continue

        # preprocess
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        gray = cv2.fastNlMeansDenoising(gray)
        gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

        # OCR multi-psm
        results = []
        for psm in [1,3,4,5,6,7,8,9,10,11,12,13]:
            text = pytesseract.image_to_string(gray, config=f"--psm {psm}")
            results.append((score_ocr(text), text))

        _, best_text = max(results, key=lambda x: x[0])

        lines = [x.strip() for x in best_text.splitlines() if x.strip()]

        # detect store
        store = "Unknown"
        for line in lines[:15]:
            c = clean_item_name(line)
            for key,val in STORE_NAMES.items():
                if key in c:
                    store = val
                    break

        # detect date
        receipt_date = ""
        for line in lines:
            m = date_pattern.search(line)
            if m:
                receipt_date = m.group()
                break

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
            """, (store, "", receipt_date, raw_name, clean, price))

            print(f"{clean} -> ${price:.2f}")

        conn.commit()

    conn.close()
    print("\nFinished.")

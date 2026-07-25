import os
import re
import cv2
import pytesseract
import sqlite3
from difflib import get_close_matches

# ----------------------------
# Configuration
# ----------------------------

RECEIPT_FOLDER = "receipts"
DATABASE = "receipts.db"
DEBUG_OCR_FILE = "debug_ocr.txt"

# ----------------------------
# Check receipt folder
# ----------------------------

if not os.path.exists(RECEIPT_FOLDER):
    print(f"Error: '{RECEIPT_FOLDER}' folder not found.")
    exit()

# ----------------------------
# Connect to database
# ----------------------------

conn = sqlite3.connect(DATABASE)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS items(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store TEXT,
    full_address TEXT,
    date TEXT,
    raw_name TEXT,
    clean_name TEXT,
    price REAL
)
""")

cur.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS idx_items
ON items(store, full_address, date, clean_name, price)
""")

# ----------------------------
# Regular Expressions
# ----------------------------

price_pattern = re.compile(
    r"(.+?)\s+\$?(\d{1,3}[.,]\d{2,3})(?:\s*[A-Z*]+)?$",
    re.IGNORECASE
)
date_pattern = re.compile(
    r'(?:\b\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}\b|'
    r'\b\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}\b|'
    r'\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4}\b|'
    r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:st|nd|rd|th)?,\s+\d{2,4}\b)',
    re.IGNORECASE
)
ignore_words = {
    "subtotal", "sub total", "tax", "total", "change",
    "cash", "visa", "mastercard", "debit", "credit",
    "balance", "payment", "amount", "thank", "items",
    "sale", "discount", "coupon"
}

# ---------------------------
#  Store Names/Other info
#----------------------------
STORE_NAMES = {
    "WALMART": "Walmart",
    "WAL-MART": "Walmart",
    "WAL MART": "Walmart",
    "WM SUPERCENTER": "Walmart",
    "COSTCO": "Costco",
    "COSTCO WHOLESALE": "Costco",
    "WINCO": "WinCo Foods",
    "WINCO FOODS": "WinCo Foods",
    "SAFEWAY": "Safeway",
    "FRED MEYER": "Fred Meyer",
    "TARGET": "Target",
    "ALBERTSONS": "Albertsons",
    "SMITHS": "Smith's",
    "KROGER": "Kroger",
    "TRADER JOES": "Trader Joe's",
    "TRADER JOE'S": "Trader Joe's",
    "WHOLE FOODS": "Whole Foods Market",
}

# ----------------------------
# Helper Functions
# ----------------------------

def clean_item_name(name):
    name = name.upper()
    name = re.sub(r"[^A-Z0-9\s]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()

def is_ignored(text):
    text = text.lower()
    return any(word in text for word in ignore_words)

# ----------------------------
# Process receipts
# ----------------------------

for filename in os.listdir(RECEIPT_FOLDER):

    if not filename.lower().endswith((".jpg", ".jpeg", ".png")):
        continue

    filepath = os.path.join(RECEIPT_FOLDER, filename)
    print(f"\nProcessing {filename}...")

    image = cv2.imread(filepath)

    if image is None:
        print("  Could not read image.")
        continue

    # ----------------------------
    # Preprocessing (Properly Indented)
    # ----------------------------

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.fastNlMeansDenoising(gray)
        
    # Extraction of the thresholded image array
    gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

'''    # ----------------------------
    # OCR (Multi-PSM Fallback Loop)
    # ----------------------------

    text = ""
    lines = []
            
    for psm in ["6", "4", "11", "5"]:
        custom_config = f"--psm {psm}"
        attempt_text = pytesseract.image_to_string(gray, config=custom_config)
                
        attempt_text = attempt_text.replace("$ ", "$")
        attempt_text = attempt_text.replace(" ,", ",")
        attempt_text = attempt_text.replace(" .", ".")
                
        attempt_lines = [line.strip() for line in attempt_text.split("\n") if line.strip()]
                
        if attempt_lines:
            text = attempt_text
            lines = attempt_lines
            print(f"  Successfully extracted text using --psm {psm}")
            break

    with open(DEBUG_OCR_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n--- {filename} ---\n{text}\n")

    if not lines:
        print("  No text found across any PSM settings.")
        continue
'''
# ----------------------------
# OCR (Multi-PSM Combine)
# ----------------------------

all_lines = []
ocr_results = {}

for psm in ["6", "4", "11", "5"]:
    config = f"--psm {psm}"

    attempt = pytesseract.image_to_string(
        gray,
        config=config
    )

    attempt = attempt.replace("$ ", "$")
    attempt = attempt.replace(" ,", ",")
    attempt = attempt.replace(" .", ".")

    lines = [
        line.strip()
        for line in attempt.splitlines()
        if line.strip()
    ]

    ocr_results[psm] = lines

    print(f"\nPSM {psm}: {len(lines)} lines")

    for line in lines:
        all_lines.append(line)


# ----------------------------
# Combine / Deduplicate
# ----------------------------

combined_lines = []

for line in all_lines:

    clean = clean_item_name(line)

    if not clean:
        continue

    duplicate = False

    for existing in combined_lines:
        existing_clean = clean_item_name(existing)

        # Similar OCR results
        if get_close_matches(
            clean,
            [existing_clean],
            cutoff=0.85
        ):
            duplicate = True
            break

    if not duplicate:
        combined_lines.append(line)


lines = combined_lines


print("\n--- COMBINED OCR ---")

for line in lines:
    print(line)
# Save debug
with open(DEBUG_OCR_FILE, "a", encoding="utf-8") as f:
    f.write("\n--- COMBINED OCR ---\n")

    for line in lines:
        f.write(line + "\n")
    # ----------------------------
    # Store detection (best guess)
    # ----------------------------
    known_stores = list(STORE_NAMES.keys())
    store = "Unknown"

    for line in lines[:20]:
        clean = clean_item_name(line)

        for key, value in STORE_NAMES.items():
            if key in clean:
                store = value
                break
        if store != "Unknown":
            break
                
        match = get_close_matches(clean, known_stores, n=1, cutoff=0.60)
        if match:
            store = STORE_NAMES[match[0]]
            break
                
    print(f"Store: {store}")

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

    # ----------------------------
    # Date detection
    # ----------------------------

    receipt_date = ""
    receipt_dates = []

    for line in lines:
        match = date_pattern.search(line)
        if match:
            receipt_dates.append(match.group())
                
    receipt_date = receipt_dates[0] if receipt_dates else ""
    if receipt_date:
        print(f"Date: {receipt_date}")
    else:
        print("No Date Found")

    # ----------------------------
    # Item extraction
    # ----------------------------

    for line in lines:
        match = price_pattern.search(line)
        if not match:
            continue

        item_raw = match.group(1).strip()
        price_text = match.group(2)

        if is_ignored(item_raw):
            continue

        price_text = price_text.replace(",", ".")

        if len(price_text.split(".")) == 3:
            price_text = price_text[:-1]

        try:
            price = float(price_text)
            clean_name = clean_item_name(item_raw)
                
            if not clean_name:
                continue

            cur.execute("""
                INSERT OR IGNORE INTO items
                (store, full_address, date, raw_name, clean_name, price)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (store, full_address, receipt_date, item_raw, clean_name, price))

            print(f"  {clean_name} -> ${price:.2f}")
        except Exception as e:
            print(f"  Error parsing row data: {e}")
            continue

    # Commit changes per receipt
    conn.commit()

# ----------------------------
# Close database (Moved outside the loop)
# ----------------------------
conn.close()
print("\nDone.")

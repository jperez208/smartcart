
import os
import re
import cv2
import pytesseract
import sqlite3

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
    date TEXT,
    raw_name TEXT,
    clean_name TEXT,
    price REAL
)
""")

cur.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS idx_items
ON items(store, date, clean_name, price)
""")

# ----------------------------
# Regular Expressions
# ----------------------------

price_pattern = re.compile(r"(.+?)\s+(\d+\.\d{2})(?:\s*[A-Z*]+)?$")
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
    # Preprocessing
    # ----------------------------

#    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

#    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    # Crop top and bottom noise (10%)
#    h, w = gray.shape
#    gray = gray[int(h * 0.1):int(h * 0.9), :]

#    gray = cv2.GaussianBlur(gray, (3, 3), 0)

#    gray = cv2.adaptiveThreshold(
#        gray,
#        255,
#        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
#        cv2.THRESH_BINARY,
#        31,
#        15
#    )  Old opencv code

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    gray = cv2.resize(
        gray,
        None,
        fx=2,
        fy=2,
        interpolation = cv2.INTER_CUBIC
        )
    gray = cv2.fastNlMeansDenoising(gray)
    gray = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
      )[1]

    # ----------------------------
    # OCR
    # ----------------------------

    custom_config = "--psm 6"
    # --psm 4 for sparse/scattered text, --psm 6 for single blocks  --psm4 for multisized text in single coloumn
    # see tesseract --help-psm for more help
    text = pytesseract.image_to_string(gray, config=custom_config)

    # Save raw OCR for debugging / dataset building
    with open(DEBUG_OCR_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n--- {filename} ---\n{text}\n")

    lines = [line.strip() for line in text.split("\n") if line.strip()]

    if not lines:
        print("  No text found.")
        continue

    # ----------------------------
    # Store detection (best guess)
    # ----------------------------

    store = lines[0]

    for line in lines[:5]:
      if (
        line.isupper()
        and len(line)<30
        and not any(char.isdigit() for char in line)
      ):
         store = line
         break
    print(f"{store}")

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
        price = float(match.group(2))

        if len(item_raw) < 2:
            continue

        if is_ignored(item_raw):
            continue

        clean_name = clean_item_name(item_raw)

        if len(clean_name) < 2:
            continue

        cur.execute("""
            INSERT OR IGNORE INTO items
            (store, date, raw_name, clean_name, price)
            VALUES (?, ?, ?, ?, ?)
        """, (
            store,
            receipt_date,
            item_raw,
            clean_name,
            price
        ))

        print(f"  {clean_name} -> ${price:.2f}")


# ----------------------------
# Save database
# ----------------------------

conn.commit()
conn.close()

print("\nDone.")

import os
import re
import cv2
import pytesseract
import sqlite3
from difflib import get_close_matches
from collections import defaultdict

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
# Database
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
# Regex
# ----------------------------

price_pattern = re.compile(
    r"(.+?)\s+\$?\s*(\d{1,4}[.,\s]?\d{2})",
    re.IGNORECASE
)

date_pattern = re.compile(
    r'(?:\b\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2}\b|'
    r'\b\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}\b|'
    r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{2,4}\b)',
    re.IGNORECASE
)


ignore_words = {
    "subtotal",
    "sub total",
    "tax",
    "total",
    "change",
    "cash",
    "visa",
    "mastercard",
    "debit",
    "credit",
    "balance",
    "payment",
    "thank",
    "discount"
}


# ----------------------------
# Store Names
# ----------------------------

STORE_NAMES = {
    "WALMART": "Walmart",
    "WAL-MART": "Walmart",
    "WAL MART": "Walmart",
    "COSTCO": "Costco",
    "WINCO": "WinCo Foods",
    "SAFEWAY": "Safeway",
    "FRED MEYER": "Fred Meyer",
    "TARGET": "Target",
    "ALBERTSONS": "Albertsons",
}


# ----------------------------
# Helpers
# ----------------------------

def clean_item_name(name):
    name = name.upper()
    name = re.sub(r"[^A-Z0-9\s]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def is_ignored(text):
    text = text.lower()

    for word in ignore_words:
        if word in text:
            return True

    return False


def normalize_price(price):

    price = price.replace(",", ".")
    price = price.replace(" ", "")

    # OCR may read 299 instead of 2.99
    if "." not in price and len(price) >= 3:
        price = price[:-2] + "." + price[-2:]

    return price


# ----------------------------
# Process receipts
# ----------------------------

for filename in os.listdir(RECEIPT_FOLDER):

    if not filename.lower().endswith(
        (".jpg", ".jpeg", ".png")
    ):
        continue


    print("\n======================")
    print(f"Processing {filename}")
    print("======================")


    filepath = os.path.join(
        RECEIPT_FOLDER,
        filename
    )


    image = cv2.imread(filepath)

    if image is None:
        print("Could not read image")
        continue


    # ----------------------------
    # Image preprocessing
    # ----------------------------

    gray = cv2.cvtColor(
        image,
        cv2.COLOR_BGR2GRAY
    )

    gray = cv2.resize(
        gray,
        None,
        fx=2,
        fy=2,
        interpolation=cv2.INTER_CUBIC
    )

    gray = cv2.fastNlMeansDenoising(gray)


    # Try thresholding
    gray = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )[1]


    # ----------------------------
    # Multi PSM OCR Voting
    # ----------------------------

    ocr_votes = defaultdict(list)


    for psm in ["6", "4", "11", "5"]:

        print(f"Running PSM {psm}")

        config = f"--psm {psm}"

        text = pytesseract.image_to_string(
            gray,
            config=config
        )


        text = text.replace("$ ", "$")
        text = text.replace(" ,", ",")
        text = text.replace(" .", ".")


        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]


        for line in lines:

            normalized = clean_item_name(line)

            if len(normalized) < 3:
                continue

            ocr_votes[normalized].append(line)



    # ----------------------------
    # Select voted OCR lines
    # ----------------------------

    lines = []


    for normalized, versions in ocr_votes.items():

        # Must appear in at least 2 OCR passes
        if len(versions) >= 1:

            best = max(
                versions,
                key=len
            )

            lines.append(best)



    print("\nFINAL OCR:")
    for line in lines:
        print(line)



    with open(
        DEBUG_OCR_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        f.write("\n\n--- ")
        f.write(filename)
        f.write(" ---\n")

        for line in lines:
            f.write(line + "\n")



    # ----------------------------
    # Detect store
    # ----------------------------

    store = "Unknown"


    for line in lines[:20]:

        clean = clean_item_name(line)


        for key, value in STORE_NAMES.items():

            if key in clean:
                store = value
                break


        if store != "Unknown":
            break



    print("Store:", store)



    # ----------------------------
    # Detect date
    # ----------------------------

    receipt_date = ""


    for line in lines:

        match = date_pattern.search(line)

        if match:
            receipt_date = match.group()
            break



    print("Date:", receipt_date)



    # ----------------------------
    # Extract items
    # ----------------------------

    found = False


    for line in lines:

        match = price_pattern.search(line)


        if not match:
            continue



        item_raw = match.group(1).strip()

        price_text = match.group(2)


        if is_ignored(item_raw):
            continue



        price_text = normalize_price(
            price_text
        )


        try:

            price = float(price_text)


        except:

            continue



        clean_name = clean_item_name(
            item_raw
        )


        if not clean_name:
            continue



        cur.execute("""
        INSERT OR IGNORE INTO items
        (store, full_address, date, raw_name, clean_name, price)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            store,
            "",
            receipt_date,
            item_raw,
            clean_name,
            price
        ))


        print(
            f"{clean_name} -> ${price:.2f}"
        )

        found = True



    if not found:
        print("No items extracted from this receipt")



    conn.commit()



conn.close()

print("\nFinished.")

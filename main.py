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
# Database Setup
# ----------------------------

def init_db():
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS items (
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
    ON items (store, full_address, date, clean_name, price)
    """)

    conn.commit()
    conn.close()

# ----------------------------
# Image Preprocessing
# ----------------------------

def preprocess(image_path):
    img = cv2.imread(image_path)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Improve contrast
    gray = cv2.convertScaleAbs(gray, alpha=1.5, beta=10)

    # Reduce noise
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    # Threshold
    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

    # Crop middle (avoid header/footer junk)
    h, w = thresh.shape
    cropped = thresh[int(h * 0.2):int(h * 0.8), :]

    return cropped

# ----------------------------
# OCR Scoring
# ----------------------------

def score_lines(lines):
    score = 0
    price_pattern = re.compile(r"\$?\d+\.\d{2}")

    for line in lines:
        if price_pattern.search(line):
            score += 3

        if 5 < len(line) < 40:
            score += 1

        if re.search(r"[^\w\s\.\-\$]", line):
            score -= 1

    return score

# ----------------------------
# OCR with Multiple PSM
# ----------------------------

def run_ocr(image):
    best_score = -1
    best_lines = []
    best_text = ""

    for psm in [6, 4, 11, 5]:
        config = f"--psm {psm}"
        attempt = pytesseract.image_to_string(image, config=config)

        lines = [l.strip() for l in attempt.splitlines() if l.strip()]
        s = score_lines(lines)

        if s > best_score:
            best_score = s
            best_lines = lines
            best_text = attempt

    # Debug save
    with open(DEBUG_OCR_FILE, "w") as f:
        f.write(best_text)

    return best_lines

# ----------------------------
# Line Filtering
# ----------------------------

def filter_lines(lines):
    filtered = []

    for line in lines:
        low = line.lower()

        if any(x in low for x in [
            "total", "tax", "change", "balance",
            "cash", "visa", "debit", "credit"
        ]):
            continue

        if re.search(r"\d+\.\d{2}", line):
            filtered.append(line)

    return filtered

# ----------------------------
# Extract Items
# ----------------------------

def extract_items(lines):
    items = []

    pattern = re.compile(r"(.+?)\s+\$?(\d+\.\d{2})")

    for line in lines:
        match = pattern.search(line)
        if match:
            raw_name = match.group(1).strip()
            price = float(match.group(2))

            clean_name = re.sub(r"[^a-zA-Z0-9\s]", "", raw_name).lower()

            items.append((raw_name, clean_name, price))

    return items

# ----------------------------
# Save to Database
# ----------------------------

def save_items(items):
    conn = sqlite3.connect(DATABASE)
    cur = conn.cursor()

    for raw, clean, price in items:
        try:
            cur.execute("""
            INSERT INTO items (store, full_address, date, raw_name, clean_name, price)
            VALUES (?, ?, ?, ?, ?, ?)
            """, ("unknown", "unknown", "unknown", raw, clean, price))
        except sqlite3.IntegrityError:
            pass  # skip duplicates

    conn.commit()
    conn.close()

# ----------------------------
# Main Processing Loop
# ----------------------------

def process_receipts():
    for file in os.listdir(RECEIPT_FOLDER):
        if not file.lower().endswith((".png", ".jpg", ".jpeg")):
            continue

        path = os.path.join(RECEIPT_FOLDER, file)
        print(f"Processing: {file}")

        image = preprocess(path)
        lines = run_ocr(image)
        lines = filter_lines(lines)
        items = extract_items(lines)

        print("Items found:")
        for item in items:
            print(item)

        save_items(items)

# ----------------------------
# Run
# ----------------------------

if __name__ == "__main__":
    init_db()
    process_receipts()

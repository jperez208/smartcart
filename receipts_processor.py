import os
import cv2
import pytesseract
import re
import hashlib
from concurrent.futures import ProcessPoolExecutor, as_completed

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
    r"(?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|\d|3)[-/.](?:\d{2}|\d{4})"
    r"|"
    r"(?:0?[1-9]|\d|3)[-/.](?:0?[1-9]|1[0-2])[-/.](?:\d{2}|\d{4})"
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
    Returns the receipt ID row.
    """

    file_hash = get_file_hash(
        filepath
    )

    cur.execute(
        """
        INSERT OR IGNORE INTO receipts
        (filename, file_hash, store_name, store_address, receipt_date)
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

    cur.execute(
        """
        SELECT id 
        FROM receipts 
        WHERE file_hash = ?
        """,
        (file_hash,),
    )
    
    result = cur.fetchone()
    return result[0] if result else None


# ---------------------------------------------------------------------------
# Multi-Core Parallel OCR Engine Worker
# ---------------------------------------------------------------------------

def process_single_file_worker(filename):
    """
    Standalone CPU-bound function to process a single receipt image.
    Executed inside worker pools out of the main database loop.
    """
    filepath = os.path.join(RECEIPT_FOLDER, filename)
    
    if not filename.lower().endswith(('.png', '.jpg', '.jpeg', '.tiff', '.bmp')):
        return None

    try:
        tesseract_config = r'--oem 3 --psm 6'
        best_text = ""
        best_count = -1
        
        img = cv2.imread(filepath)
        if img is None:
            return None
            
        text = pytesseract.image_to_string(img, config=tesseract_config)
        count = count_item_matches(text)
        if count > best_count:
            best_count = count
            best_text = text

        if best_count < MIN_GOOD_ITEMS:
            for variant in FALLBACK_VARIANT_NAMES:
                processed_img = preprocess_receipt(filepath, variant, OCR_WIDTH)
                if processed_img is not None:
                    v_text = pytesseract.image_to_string(processed_img, config=tesseract_config)
                    v_count = count_item_matches(v_text)

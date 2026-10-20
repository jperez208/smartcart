
import re


# ---------------------------------------------------------------------------
# Receipt lines that should not be treated as purchased items
# ---------------------------------------------------------------------------

IGNORE_WORDS = {
    "SUBTOTAL",
    "SUB TOTAL",
    "SUBTCTAL",
    "SUBT0TAL",
    "GRAND TOTAL",
    "TOTAL",
    "TAX",
    "CHANGE",
    "CASH",
    "ACCOUNT",
    "APPROVAL",
    "REFERENCE",
    "TRANS",
    "TRANSACTION",
    "VALIDATION",
    "TERMINAL",
    "PAYMENT",
    "SERVICE",
    "VISA",
    "MASTERCARD",
    "DEBIT",
    "CREDIT",
    "THANK",
    "AMOUNT",
    "PURCHASE",
    "BALANCE",
    "TENDERS",
    "SUMMARY",
}

IGNORE_WHOLE = {"REF"}

# Compile once rather than rebuilding the patterns for every line.
IGNORE_PATTERNS = [
    re.compile(
        r"(?<![A-Z])"
        + re.escape(word)
        + r"(?![A-Z])"
    )
    for word in sorted(IGNORE_WORDS, key=len, reverse=True)
]

# OCR frequently confuses letters and digits in receipt totals.
OCR_TOTAL_PATTERN = re.compile(
    r"\bSUBT[O0C]?T[AO0]L\b"
    r"|\bGRAND\s+T[O0]TAL\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Store names
# ---------------------------------------------------------------------------

STORE_NAMES = {
    "WALMART": "Walmart",
    "WAL MART": "Walmart",
    "WALMART STORE": "Walmart",
    "COSTCO": "Costco",
    "WINCO": "WinCo Foods",
    "SAFEWAY": "Safeway",
    "TARGET": "Target",
    "DOLLAR TREE": "Dollar Tree",
    "DOLLARTREE": "Dollar Tree",
}


# ---------------------------------------------------------------------------
# Item-name cleaning
# ---------------------------------------------------------------------------

def clean_item_name(name):
    """Normalize an OCR item name for matching and storage."""

    name = str(name).upper()
    name = re.sub(r"[^A-Z0-9\s]", "", name)
    name = re.sub(r"\s+", " ", name)

    return name.strip()


# ---------------------------------------------------------------------------
# Ignore non-item lines
# ---------------------------------------------------------------------------

def ignored(line):
    """
    Return True for receipt summary, payment, or transaction lines.

    Uses word boundaries to avoid rejecting legitimate products merely
    because their names contain a substring such as CASH or TOTAL.
    """

    if not line:
        return True

    upper = str(line).upper().strip()

    if not upper:
        return True

    # Normalize whitespace for phrases such as SUB TOTAL.
    normalized = re.sub(r"\s+", " ", upper)

    # Handle common OCR mistakes in subtotal and total labels.
    if OCR_TOTAL_PATTERN.search(normalized):
        return True

    # Match configured words and phrases without substring collisions.
    if any(pattern.search(normalized) for pattern in IGNORE_PATTERNS):
        return True

    tokens = set(re.findall(r"[A-Z]+", normalized))

    if tokens & IGNORE_WHOLE:
        return True

    return False


# ---------------------------------------------------------------------------
# Price normalization
# ---------------------------------------------------------------------------

def normalize_price(value):
    """Normalize OCR price strings into float-friendly decimal notation."""

    value = str(value).strip()
    value = value.replace(" ", "").replace("$", "")

    # US thousands: 1,299.99 -> 1299.99
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(\.\d{2})?", value):
        return value.replace(",", "")

    # European-style: 1.299,99 -> 1299.99
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+,\d{2}", value):
        return value.replace(".", "").replace(",", ".")

    # Bare comma decimals: 1,99 -> 1.99
    if re.fullmatch(r"\d+,\d{2}", value):
        return value.replace(",", ".")

    return value


# ---------------------------------------------------------------------------
# OCR scoring
# ---------------------------------------------------------------------------

def score_ocr(text):
    """Tie-breaker score; item-line count should remain the primary key."""

    if not text:
        return -999

    score = len(text) // 20
    score += len(re.findall(r"\d+\.\d{2}", text)) * 15

    upper = text.upper()

    for word in ("TOTAL", "TAX", "SUBTOTAL", "PRICE", "ITEM"):
        if word in upper:
            score += 20

    return score

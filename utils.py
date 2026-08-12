import re

IGNORE_WORDS = [
    "SUBTOTAL", "SUB TOTAL", "TOTAL", "TAX", "CHANGE", "CASH",
    "ACCOUNT", "APPROVAL", "REFERENCE", "TRANS", "TRANSACTION",
    "VALIDATION", "TERMINAL", "PAYMENT", "SERVICE", "VISA",
    "MASTERCARD", "DEBIT", "CREDIT", "THANK",
    "AMOUNT", "PURCHASE", "BALANCE", "TENDERS", "SUMMARY",
]

# Short tokens that must match as whole words (avoid "REF" inside other words)
IGNORE_WHOLE = {"REF"}

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


def clean_item_name(name):
    name = name.upper()
    name = re.sub(r"[^A-Z0-9\s]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()


def ignored(line):
    upper = line.upper()
    if any(word in upper for word in IGNORE_WORDS):
        return True
    tokens = set(re.findall(r"[A-Z]+", upper))
    return bool(tokens & IGNORE_WHOLE)


def normalize_price(value):
    """Normalize OCR price strings to a float-friendly form."""
    value = value.strip().replace(" ", "").replace("$", "")
    # US thousands: 1,299.99 -> 1299.99
    if re.match(r"^\d{1,3}(,\d{3})+(\.\d{2})?$", value):
        return value.replace(",", "")
    # European-style: 1.299,99 -> 1299.99
    if re.match(r"^\d{1,3}(\.\d{3})+(,\d{2})$", value):
        return value.replace(".", "").replace(",", ".")
    # Bare comma decimals: 1,99 -> 1.99
    if re.match(r"^\d+,\d{2}$", value):
        return value.replace(",", ".")
    return value


def score_ocr(text):
    """Tie-breaker only. Item-line count should be the primary ranking key."""
    if not text:
        return -999

    score = 0
    score += len(text) // 20
    score += len(re.findall(r"\d+\.\d{2}", text)) * 15

    upper = text.upper()
    for word in ("TOTAL", "TAX", "SUBTOTAL", "PRICE", "ITEM"):
        if word in upper:
            score += 20

    return score

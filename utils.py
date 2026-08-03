import re

IGNORE_WORDS = [
    "SUBTOTAL","SUB TOTAL","TOTAL","TAX","CHANGE","CASH",
    "ACCOUNT","APPROVAL","REFERENCE","REF","TRANS","TRANSACTION",
    "VALIDATION","TERMINAL","PAYMENT","SERVICE","VISA",
    "MASTERCARD","DEBIT","CREDIT","THANK"
]

STORE_NAMES = {
    "WALMART": "Walmart",
    "WAL MART": "Walmart",
    "WALMART STORE": "Walmart",

    "WALMART": "Walmart",
    "COSTCO": "Costco",
    "WINCO": "WinCo Foods",
    "SAFEWAY": "Safeway",
    "TARGET": "Target",

    "DOLLAR TREE": "Dollar Tree",
    "DOLLARTREE": "Dollar Tree",
    "DOLLAR  TREE": "Dollar Tree"
}

def clean_item_name(name):
    name = name.upper()
    name = re.sub(r"[^A-Z0-9\s]", "", name)
    name = re.sub(r"\s+", " ", name)
    return name.strip()

def ignored(line):
    upper = line.upper()
    return any(word in upper for word in IGNORE_WORDS)

def normalize_price(value):
    return value.replace(",", ".").replace(" ", "")

def score_ocr(text):

    if not text:
        return -999

    score = 0

    score += len(text) // 20

    score += len(
        re.findall(r'\d+\.\d{2}', text)
    ) * 15

    words = [
        "TOTAL",
        "TAX",
        "SUBTOTAL",
        "PRICE",
        "ITEM"
    ]

    upper = text.upper()

    for word in words:
        if word in upper:
            score += 20

    return score

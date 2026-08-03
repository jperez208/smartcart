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
        return -100

    score = 0

    lines = [
        x.strip()
        for x in text.splitlines()
        if x.strip()
    ]

    # More readable lines = better
    score += min(len(lines), 20)

    # Reward prices
    prices = re.findall(
        r'\d+\.\d{2}',
        text
    )

    score += len(prices) * 10


    # Reward currency
    score += text.count("$") * 5


    # Reward letters
    letters = sum(
        c.isalpha()
        for c in text
    )

    score += min(
        letters // 20,
        30
    )


    # Penalize garbage
    garbage = sum(
        not(c.isalnum() or c in " $.,-/")
        for c in text
    )

    score -= garbage * 2


    # Too short is bad
    if len(text) < 50:
        score -= 20


    return score

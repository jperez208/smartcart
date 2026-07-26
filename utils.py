import re

IGNORE_WORDS = [
    "SUBTOTAL","SUB TOTAL","TOTAL","TAX","CHANGE","CASH",
    "ACCOUNT","APPROVAL","REFERENCE","REF","TRANS","TRANSACTION",
    "VALIDATION","TERMINAL","PAYMENT","SERVICE","VISA",
    "MASTERCARD","DEBIT","CREDIT","THANK"
]

STORE_NAMES = {
    "WALMART": "Walmart",
    "WAL-MART": "Walmart",
    "COSTCO": "Costco",
    "WINCO": "WinCo Foods",
    "SAFEWAY": "Safeway",
    "TARGET": "Target",
    "DOLLAR TREE": "Dollar Tree"
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
    score = 0
    upper = text.upper()

    good = ["TOTAL","SUBTOTAL","TAX","$"]
    bad = ["eeee","||||","~~~~"]

    for x in good:
        if x in upper:
            score += 10

    for x in bad:
        if x in upper:
            score -= 10

    weird = len(re.findall(r"[^A-Za-z0-9\s$.,#:/()-]", text))
    score -= weird

    return score

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
    r"(.+?)\s+\$?\s*(\d+[.,]\d{2})",
    re.IGNORECASE
)


date_pattern = re.compile(
    r'\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b',
    re.IGNORECASE
)


# ----------------------------
# Ignore words
# ----------------------------

IGNORE_WORDS = [
    "SUBTOTAL",
    "SUB TOTAL",
    "TOTAL",
    "TAX",
    "CHANGE",
    "CASH",
    "ACCOUNT",
    "APPROVAL",
    "REFERENCE",
    "REF",
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
    "THANK"
]


# ----------------------------
# Stores
# ----------------------------

STORE_NAMES = {
    "WALMART": "Walmart",
    "WAL-MART": "Walmart",
    "COSTCO": "Costco",
    "WINCO": "WinCo Foods",
    "SAFEWAY": "Safeway",
    "TARGET": "Target"
}


# ----------------------------
# Helpers
# ----------------------------

def clean_item_name(name):

    name = name.upper()

    name = re.sub(
        r"[^A-Z0-9\s]",
        "",
        name
    )

    name = re.sub(
        r"\s+",
        " ",
        name
    )

    return name.strip()



def ignored(line):

    upper = line.upper()

    for word in IGNORE_WORDS:

        if word in upper:
            return True

    return False



def normalize_price(value):

    value = value.replace(",", ".")
    value = value.replace(" ", "")

    return value



def score_ocr(text):

    score = 0

    upper = text.upper()


    good = [
        "TOTAL",
        "SUBTOTAL",
        "TAX",
        "$",
        "WALMART"
    ]


    bad = [
        "eeee",
        "||||",
        "~~~~"
    ]


    for x in good:

        if x in upper:
            score += 10


    for x in bad:

        if x in upper:
            score -= 10


    # Penalize massive garbage OCR

    weird = len(
        re.findall(
            r"[^A-Za-z0-9\s$.,#:/()-]",
            text
        )
    )

    score -= weird


    return score



# ----------------------------
# Process receipts
# ----------------------------

for filename in os.listdir(RECEIPT_FOLDER):

    if not filename.lower().endswith(
        (".png",".jpg",".jpeg")
    ):
        continue


    print("\n======================")
    print("Processing", filename)
    print("======================")


    path = os.path.join(
        RECEIPT_FOLDER,
        filename
    )


    image = cv2.imread(path)

    if image is None:
        continue



    # ----------------------------
    # Preprocess
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


    gray = cv2.threshold(
        gray,
        0,
        255,
        cv2.THRESH_BINARY +
        cv2.THRESH_OTSU
    )[1]



    # ----------------------------
    # OCR selection
    # ----------------------------

    results = []

    #original 6,4,11,5
    for psm in [1,3,4,5,6,7,8,9,10,11,12,13]:

        print("Running PSM",psm)


        text = pytesseract.image_to_string(
            gray,
            config=f"--psm {psm}"
        )


        text = text.replace("$ ","$")
        text = text.replace(" ,",",")
        text = text.replace(" .",".")


        results.append(
            (
                score_ocr(text),
                text
            )
        )



    best_score,best_text = max(
        results,
        key=lambda x:x[0]
    )


    print(
        "Selected OCR score:",
        best_score
    )


    lines = [
        x.strip()
        for x in best_text.splitlines()
        if x.strip()
    ]


#    print("\nFINAL OCR:")

 #   for line in lines:
  #      print(line)



    with open(
        DEBUG_OCR_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        f.write("\n\n---"+filename+"---\n")

        for line in lines:
            f.write(line+"\n")



    # ----------------------------
    # Store
    # ----------------------------

    store="Unknown"


    for line in lines[:15]:

        c=clean_item_name(line)

        for key,val in STORE_NAMES.items():

            if key in c:
                store=val
                break


    print("Store:",store)



    # ----------------------------
    # Date
    # ----------------------------

    receipt_date=""

    for line in lines:

        m=date_pattern.search(line)

        if m:
            receipt_date=m.group()
            break


    print("Date:",receipt_date)



    # ----------------------------
    # Items only
    # ----------------------------

    reading_items=True


    found=False


    for line in lines:


        if "SUBTOTAL" in line.upper():

            reading_items=False


        if not reading_items:
            continue



        match=price_pattern.search(line)


        if not match:
            continue



        raw_name=match.group(1).strip()

        price=normalize_price(
            match.group(2)
        )


        if ignored(raw_name):
            continue



        try:

            price=float(price)

        except:

            continue



        # Reject impossible prices

        if price <=0 or price>500:

            continue



        clean=clean_item_name(raw_name)


        if len(clean)<3:

            continue



        cur.execute("""
        INSERT OR IGNORE INTO items
        (store,full_address,date,raw_name,clean_name,price)
        VALUES (?,?,?,?,?,?)
        """,
        (
            store,
            full_address,
            receipt_date,
            raw_name,
            clean,
            price
        ))


        print(
            f"{clean} -> ${price:.2f}"
        )


        found=True



    if not found:

        print("No items extracted")


    conn.commit()



conn.close()

print("\nFinished.")

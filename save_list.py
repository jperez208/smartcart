import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ITEM_FILE = os.path.join(BASE_DIR, "items.txt")


def append_list(store, receipt_date, full_address, items):
    with open(ITEM_FILE, "a", encoding="utf-8") as f:
        f.write("Store: " + store + "\n")
        f.write("Address: " + full_address + "\n")
        f.write("Date: " + receipt_date + "\n")

        for clean, price in items:
            f.write(f"{clean}: ${price:.2f}\n")

        f.write("\n")

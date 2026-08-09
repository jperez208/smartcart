import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ITEM_FILE = os.path.join(BASE_DIR, "items.txt")

def append_list(store, receipt_date, full_address, clean, price):
    with open(ITEM_FILE, "a", encoding="utf-8") as f:
            f.write("Store:")
            f.write(store + "\n")
            f.write("Address:")
            f.write(full_address + "\n")
            f.write("Date:")
            f.write(receipt_date + "\n")
            
                    

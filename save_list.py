import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ITEM_FILE = os.path.join(BASE_DIR, "items.txt")

def append_list(store):
    with open(ITEM_FILE, "a", encoding="utf-8") as f:
            f.write("Store:")
            f.write(store + "\n")

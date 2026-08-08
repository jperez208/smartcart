import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ITEM_FILE = os.path.join(BASE_DIR, "items.txt")

def append_list(lines):
    with open(ITEM_FILE, "a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")

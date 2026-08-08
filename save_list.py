import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

ITEM_FILE = os.path.join(BASE_DIR, "items.txt")

def append_list():
  with open(ITEM_FILE, "a", encoding="utf-8") as f:
              f.write(f"\n\n--- {filename} ---\n")
              f.write(f"Method: {best_method}, PSM: {best_psm}\n\n")
              for line in lines:
                  f.write(line + "\n")

if __name__=="__main__":
  save_list()

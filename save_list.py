import os

def append_list():
  with open(DEBUG_OCR_FILE, "a", encoding="utf-8") as f:
              f.write(f"\n\n--- {filename} ---\n")
              f.write(f"Method: {best_method}, PSM: {best_psm}\n\n")
              for line in lines:
                  f.write(line + "\n")

if __name__=="__main__":
  save_list()

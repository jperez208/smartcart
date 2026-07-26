from db import init_db
from receipts_processor import process_receipts

def main():
    init_db()
    process_receipts()

if __name__ == "__main__":
    main()

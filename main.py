from db import init_db
from receipts_processor import process_receipts
from import_receipts_to_master import run_import

def main():
    init_db()
    process_receipts()
    run_import()

if __name__ == "__main__":
    main()

from db import init_db
from receipts_processor import process_receipts
from import_receipts_to_master import run_import
from compare_products import run_comparison

def main():
    init_db()
    process_receipts()
    run_import()
    run_comparison()

if __name__ == "__main__":
    main()

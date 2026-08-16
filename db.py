# db.py

import sqlite3


DATABASE = "receipts.db"


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

def get_connection():
    """
    Open the local receipts database.
    """

    return sqlite3.connect(DATABASE)


# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------

def init_db():
    """
    Create the receipt-side database tables and indexes.

    receipts.db is the historical/raw receipt database.

    It should contain what the OCR system actually found.

    Product comparison and canonical product information will eventually
    live in master.db.
    """

    conn = get_connection()
    cur = conn.cursor()

    # -----------------------------------------------------------------------
    # Receipt items
    # -----------------------------------------------------------------------
    #
    # Each row represents an item found on a receipt.
    #
    # IMPORTANT:
    # raw_name is what OCR/parser originally saw.
    #
    # clean_name is the cleaned version used by the current parser.
    #
    # We intentionally do NOT store canonical product information here.
    #
    # That belongs in master.db.
    #

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            store TEXT,

            full_address TEXT,

            date TEXT,

            raw_name TEXT NOT NULL,

            clean_name TEXT NOT NULL,

            price REAL
        )
        """
    )

    # -----------------------------------------------------------------------
    # Prevent duplicate receipt items
    # -----------------------------------------------------------------------
    #
    # This is retained from the previous version.
    #
    # NOTE:
    # Two genuinely separate purchases of the same item at the same price
    # on the same receipt could theoretically collide here.
    #
    # We'll improve receipt identity later if needed.
    #

    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_items
        ON items(
            store,
            full_address,
            date,
            clean_name,
            price
        )
        """
    )

    # -----------------------------------------------------------------------
    # Processed receipt files
    # -----------------------------------------------------------------------
    #
    # This prevents the same image from being processed repeatedly.
    #

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_files(
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            filename TEXT UNIQUE,

            file_hash TEXT UNIQUE,

            processed_date
                TIMESTAMP
                DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # -----------------------------------------------------------------------
    # OLD PRODUCTS TABLE
    # -----------------------------------------------------------------------
    #
    # This table is kept temporarily for compatibility with older versions
    # of SmartCart.
    #
    # NEW CODE SHOULD NOT USE THIS TABLE.
    #
    # The future master product database will live in:
    #
    #     master.db
    #
    # and will be populated by compare_products.py.
    #
    # We are deliberately not deleting this table yet because an existing
    # receipts.db may already contain product information.
    #

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            canonical_name TEXT NOT NULL,

            brand TEXT,

            size TEXT,

            upc TEXT,

            sku TEXT,

            plu TEXT
        )
        """
    )

    # UPC index
    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_products_upc
        ON products(upc)
        WHERE upc IS NOT NULL
        """
    )

    # SKU index
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_products_sku
        ON products(sku)
        """
    )

    # PLU index
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_products_plu
        ON products(plu)
        """
    )

    # -----------------------------------------------------------------------
    # Commit
    # -----------------------------------------------------------------------

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    init_db()

    print(
        "receipts.db initialized successfully."
    )

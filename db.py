# db.py

import sqlite3


DATABASE = "receipts.db"


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

def get_connection():
    """
    Open the local receipts database.

    Foreign keys are enabled so receipt -> item relationships
    are enforced by SQLite.
    """

    conn = sqlite3.connect(DATABASE)

    conn.execute("PRAGMA foreign_keys = ON")

    return conn


# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------

def init_db():
    """
    Initialize / migrate the receipt database.

    receipts.db stores historical receipt observations.

    It is NOT the master product database.

    The future structure will be:

        receipts.db
            receipts
                |
                +--- items

        master.db
            products
                |
                +--- aliases
                +--- identifiers
                +--- price history
    """

    conn = get_connection()
    cur = conn.cursor()

    # -----------------------------------------------------------------------
    # Receipts
    # -----------------------------------------------------------------------
    #
    # One row represents one physical receipt image.
    #
    # This gives every receipt its own identity.
    #

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS receipts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            filename TEXT,

            file_hash TEXT UNIQUE,

            store TEXT,

            full_address TEXT,

            date TEXT,

            created_date
                TIMESTAMP
                DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # -----------------------------------------------------------------------
    # Receipt items
    # -----------------------------------------------------------------------
    #
    # Existing databases may already have this table.
    #
    # We therefore create it first, then add the new columns below
    # if they don't already exist.
    #

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            receipt_id INTEGER,

            line_number INTEGER,

            store TEXT,

            full_address TEXT,

            date TEXT,

            raw_name TEXT NOT NULL,

            clean_name TEXT NOT NULL,

            price REAL,

            FOREIGN KEY(receipt_id)
                REFERENCES receipts(id)
                ON DELETE CASCADE
        )
        """
    )

    # -----------------------------------------------------------------------
    # Migrate an older items table
    # -----------------------------------------------------------------------
    #
    # If your existing items table was created by the older version,
    # receipt_id and line_number won't exist.
    #
    # SQLite allows us to add these columns without destroying existing data.
    #

    cur.execute(
        "PRAGMA table_info(items)"
    )

    existing_columns = {
        row[1]
        for row in cur.fetchall()
    }

    if "receipt_id" not in existing_columns:

        cur.execute(
            """
            ALTER TABLE items
            ADD COLUMN receipt_id INTEGER
            """
        )

    if "line_number" not in existing_columns:

        cur.execute(
            """
            ALTER TABLE items
            ADD COLUMN line_number INTEGER
            """
        )

    # -----------------------------------------------------------------------
    # Remove old item uniqueness rule
    # -----------------------------------------------------------------------
    #
    # The previous database used:
    #
    #     store + address + date + clean_name + price
    #
    # as a unique combination.
    #
    # That is not appropriate once we track individual receipts.
    #
    # For example, two identical products bought on two different receipts
    # should remain two separate historical observations.
    #

    cur.execute(
        """
        DROP INDEX IF EXISTS idx_items
        """
    )

    # -----------------------------------------------------------------------
    # Item indexes
    # -----------------------------------------------------------------------

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_items_receipt
        ON items(receipt_id)
        """
    )

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_items_name
        ON items(clean_name)
        """
    )

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_items_store
        ON items(store)
        """
    )

    # -----------------------------------------------------------------------
    # Processed files
    # -----------------------------------------------------------------------
    #
    # This continues to prevent the same image from being processed twice.
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
    # Keep this temporarily for compatibility with an existing database.
    #
    # NEW code should NOT use this table.
    #
    # Eventually this will be replaced by master.db.
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

    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_products_upc
        ON products(upc)
        WHERE upc IS NOT NULL
        """
    )

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_products_sku
        ON products(sku)
        """
    )

    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_products_plu
        ON products(plu)
        """
    )

    # -----------------------------------------------------------------------
    # Commit changes
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

import sqlite3
from pathlib import Path


RECEIPTS_DB = Path("receipts.db")
MASTER_DB = Path("master.db")


def connect_database(path):
    """Connect to a SQLite database."""
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")

    return sqlite3.connect(path)


def get_receipt_items(receipts_conn):
    """
    Read historical receipt items from receipts.db.

    The old products table is intentionally not used.
    """
    cursor = receipts_conn.cursor()

    cursor.execute("""
        SELECT
            id,
            receipt_id,
            line_number,
            store,
            full_address,
            date,
            raw_name,
            clean_name,
            price
        FROM items
        ORDER BY id
    """)

    return cursor.fetchall()


def observation_exists(master_conn, receipt_item_id):
    """Check whether a receipt item has already been imported."""
    cursor = master_conn.cursor()

    cursor.execute("""
        SELECT id
        FROM product_observations
        WHERE receipt_item_id = ?
        LIMIT 1
    """, (receipt_item_id,))

    return cursor.fetchone() is not None


def create_observation(master_conn, receipt_item_id):
    """
    Create a raw product observation.

    No product matching is performed here.
    """
    cursor = master_conn.cursor()

    cursor.execute("""
        INSERT INTO product_observations (
            receipt_item_id,
            product_id,
            match_status,
            confidence
        )
        VALUES (?, NULL, 'unmatched', NULL)
    """, (receipt_item_id,))


def import_observations():
    """Import receipt items into master.db as product observations."""

    receipts_conn = connect_database(RECEIPTS_DB)
    master_conn = connect_database(MASTER_DB)

    try:
        items = get_receipt_items(receipts_conn)

        imported = 0
        skipped = 0

        for item in items:
            receipt_item_id = item[0]

            if observation_exists(master_conn, receipt_item_id):
                skipped += 1
                continue

            create_observation(master_conn, receipt_item_id)
            imported += 1

        master_conn.commit()

        print("Product comparison import complete.")
        print(f"Receipt items found: {len(items)}")
        print(f"New observations:    {imported}")
        print(f"Already imported:    {skipped}")

    finally:
        receipts_conn.close()
        master_conn.close()


if __name__ == "__main__":
    import_observations()

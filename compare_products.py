import sqlite3
from pathlib import Path

from product_matcher import extract_identifiers


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

    row = cursor.fetchone()

    if row:
        return row[0]

    return None


def create_observation(
    master_conn,
    receipt_item_id,
    store,
    full_address,
    date,
    raw_name,
    clean_name,
    price,
):
    """
    Create a raw product observation.

    No product matching is performed here.
    """
    cursor = master_conn.cursor()

    cursor.execute("""
        INSERT INTO product_observations (
            receipt_item_id,
            raw_name,
            clean_name,
            price,
            store,
            full_address,
            date,
            product_id,
            match_status,
            confidence
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, NULL, 'unmatched', NULL
        )
    """, (
        receipt_item_id,
        raw_name,
        clean_name,
        price,
        store,
        full_address,
        date,
    ))

    return cursor.lastrowid


def save_identifier_observations(
    master_conn,
    observation_id,
    raw_name,
    clean_name,
):
    """
    Extract possible identifiers from the receipt item's OCR text
    and save them as raw identifier observations.

    This function does NOT decide whether an identifier actually
    belongs to a product.

    It also does NOT associate the identifier with a canonical
    product.
    """
    cursor = master_conn.cursor()

    lines = []

    if raw_name:
        lines.append(raw_name)

    if clean_name and clean_name != raw_name:
        lines.append(clean_name)

    seen = set()

    for line in lines:
        identifiers = extract_identifiers(line)

        for identifier in identifiers:
            identifier_type = identifier["type"]
            identifier_value = identifier["identifier"]
            valid = identifier["valid"]

            key = (
                identifier_type,
                identifier_value,
            )

            if key in seen:
                continue

            seen.add(key)

            # This confidence is extraction confidence only.
            #
            # It is NOT a product-match confidence.
            #
            # Valid UPC/EAN values receive stronger extraction
            # confidence than possible PLU/invalid identifiers.
            if valid:
                extraction_confidence = 1.0
            else:
                extraction_confidence = 0.5

            cursor.execute("""
                INSERT OR IGNORE INTO observation_identifiers (
                    observation_id,
                    identifier_type,
                    identifier_value,
                    confidence
                )
                VALUES (?, ?, ?, ?)
            """, (
                observation_id,
                identifier_type,
                identifier_value,
                extraction_confidence,
            ))


def import_observations():
    """
    Import receipt items into master.db as raw product observations.

    This is intentionally NOT a product matching operation.
    """
    receipts_conn = connect_database(RECEIPTS_DB)
    master_conn = connect_database(MASTER_DB)

    # Enable foreign-key enforcement for this connection.
    master_conn.execute("PRAGMA foreign_keys = ON")

    try:
        items = get_receipt_items(receipts_conn)

        imported = 0
        skipped = 0
        identifiers_found = 0

        for item in items:
            (
                receipt_item_id,
                receipt_id,
                line_number,
                store,
                full_address,
                date,
                raw_name,
                clean_name,
                price,
            ) = item

            existing_observation_id = observation_exists(
                master_conn,
                receipt_item_id,
            )

            if existing_observation_id is not None:
                skipped += 1
                continue

            observation_id = create_observation(
                master_conn=master_conn,
                receipt_item_id=receipt_item_id,
                store=store,
                full_address=full_address,
                date=date,
                raw_name=raw_name,
                clean_name=clean_name,
                price=price,
            )

            save_identifier_observations(
                master_conn=master_conn,
                observation_id=observation_id,
                raw_name=raw_name,
                clean_name=clean_name,
            )

            imported += 1

        # Count identifier observations created during this run.
        cursor = master_conn.cursor()

        cursor.execute("""
            SELECT COUNT(*)
            FROM observation_identifiers
        """)

        identifiers_found = cursor.fetchone()[0]

        master_conn.commit()

        print("Product comparison import complete.")
        print("----------------------------------")
        print(f"Receipt items found:       {len(items)}")
        print(f"New observations:          {imported}")
        print(f"Already imported:          {skipped}")
        print(f"Identifier observations:   {identifiers_found}")

    except Exception:
        master_conn.rollback()
        raise

    finally:
        receipts_conn.close()
        master_conn.close()


if __name__ == "__main__":
    import_observations()

import sqlite3
from pathlib import Path

from product_matcher import (
    build_product_observation,
    extract_identifiers,
)


RECEIPTS_DB = Path("receipts.db")
MASTER_DB = Path("master.db")


def connect_database(path):
    if not path.exists():
        raise FileNotFoundError(
            f"Database not found: {path}"
        )

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    return conn


# ---------------------------------------------------------------------------
# Observation import
# ---------------------------------------------------------------------------

def observation_exists(master_cur, receipt_item_id):
    """
    Return the existing master observation ID for a receipts.db item.

    receipt_item_id is UNIQUE in product_observations, so this makes the
    importer safely repeatable.
    """

    master_cur.execute(
        """
        SELECT id
        FROM product_observations
        WHERE receipt_item_id = ?
        """,
        (receipt_item_id,),
    )

    row = master_cur.fetchone()

    if row is None:
        return None

    return row["id"]


def create_observation(
    master_cur,
    item,
):
    """
    Create one product_observations record.

    This function does NOT assign a canonical product.
    """

    existing_id = observation_exists(
        master_cur,
        item["id"],
    )

    if existing_id is not None:
        return existing_id, False

    observation = build_product_observation(
        raw_name=item["raw_name"],
        clean_name=item["clean_name"],
        price=item["price"],
        store=item["store"],
        location=item["full_address"],
        date=item["date"],
    )

    master_cur.execute(
        """
        INSERT INTO product_observations
        (
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
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'unmatched', NULL)
        """,
        (
            item["id"],
            observation["raw_name"],
            observation["clean_name"],
            observation["price"],
            observation["store"],
            observation["location"],
            observation["date"],
        ),
    )

    return master_cur.lastrowid, True


# ---------------------------------------------------------------------------
# Identifier import
# ---------------------------------------------------------------------------

def import_identifiers(
    master_cur,
    observation_id,
    raw_name,
    clean_name,
):
    """
    Extract all identifiers from the receipt observation and store them
    in observation_identifiers.

    Existing identifiers are ignored.
    """

    texts = []

    if raw_name:
        texts.append(str(raw_name))

    if clean_name:
        texts.append(str(clean_name))

    # Avoid processing the exact same text twice.
    texts = list(dict.fromkeys(texts))

    identifiers = []

    for text in texts:
        identifiers.extend(
            extract_identifiers(text)
        )

    inserted = 0

    # Prevent duplicate identifiers returned by multiple OCR fields.
    seen = set()

    for identifier in identifiers:

        identifier_type = identifier.get(
            "type"
        )

        identifier_value = identifier.get(
            "identifier"
        )

        valid = identifier.get(
            "valid",
            False,
        )

        confidence = identifier.get(
            "confidence"
        )

        if not identifier_type:
            continue

        if not identifier_value:
            continue

        identifier_type = str(
            identifier_type
        ).strip().upper()

        identifier_value = str(
            identifier_value
        ).strip()

        key = (
            identifier_type,
            identifier_value,
        )

        if key in seen:
            continue

        seen.add(key)

        # If product_matcher does not provide an explicit confidence,
        # derive a conservative value from validity.
        if confidence is None:
            confidence = (
                1.0
                if valid
                else 0.50
            )

        master_cur.execute(
            """
            INSERT OR IGNORE INTO observation_identifiers
            (
                observation_id,
                identifier_type,
                identifier_value,
                confidence
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                observation_id,
                identifier_type,
                identifier_value,
                confidence,
            ),
        )

        if master_cur.rowcount:
            inserted += 1

    return inserted


# ---------------------------------------------------------------------------
# Import one receipt item
# ---------------------------------------------------------------------------

def import_item(
    master_cur,
    item,
):
    """
    Import one receipts.db item.

    Returns:

        observation_id
        observation_created
        identifiers_created
    """

    observation_id, created = create_observation(
        master_cur,
        item,
    )

    identifiers_created = import_identifiers(
        master_cur,
        observation_id,
        item["raw_name"],
        item["clean_name"],
    )

    return (
        observation_id,
        created,
        identifiers_created,
    )


# ---------------------------------------------------------------------------
# Main importer
# ---------------------------------------------------------------------------

def run_import():
    print()
    print("SmartCart receipt → master importer")
    print("------------------------------------")

    receipts_conn = connect_database(
        RECEIPTS_DB
    )

    master_conn = connect_database(
        MASTER_DB
    )

    # Required because master.db uses foreign keys.
    master_conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    receipts_cur = receipts_conn.cursor()
    master_cur = master_conn.cursor()

    observations_created = 0
    observations_existing = 0
    identifiers_created = 0
    items_seen = 0

    try:

        receipts_cur.execute(
            """
            SELECT
                id,
                raw_name,
                clean_name,
                price,
                store,
                full_address,
                date
            FROM items
            ORDER BY id
            """
        )

        rows = receipts_cur.fetchall()

        print(
            f"Receipt items found: {len(rows)}"
        )

        for item in rows:

            items_seen += 1

            (
                observation_id,
                created,
                identifier_count,
            ) = import_item(
                master_cur,
                item,
            )

            if created:
                observations_created += 1

                print(
                    f"Imported item {item['id']} "
                    f"→ observation {observation_id}: "
                    f"{item['clean_name']}"
                )

            else:
                observations_existing += 1

                print(
                    f"Already imported item "
                    f"{item['id']} "
                    f"→ observation {observation_id}"
                )

            identifiers_created += (
                identifier_count
            )

        master_conn.commit()

        print()
        print("Import complete.")
        print("----------------")
        print(
            f"Items examined:           "
            f"{items_seen}"
        )
        print(
            f"New observations:         "
            f"{observations_created}"
        )
        print(
            f"Existing observations:    "
            f"{observations_existing}"
        )
        print(
            f"New identifiers:          "
            f"{identifiers_created}"
        )

    except Exception:
        master_conn.rollback()
        raise

    finally:
        receipts_conn.close()
        master_conn.close()


if __name__ == "__main__":
    run_import()

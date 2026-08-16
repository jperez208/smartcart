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
    """Return the existing observation ID, if already imported."""

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


def create_provisional_product(master_conn, clean_name):
    """
    Create a provisional canonical product.

    This is NOT a confirmed product identity.

    It simply gives an observation a product record that can be used
    as a candidate target while the learning system is being built.
    """

    cursor = master_conn.cursor()

    canonical_name = clean_name or "UNKNOWN PRODUCT"

    cursor.execute("""
        INSERT INTO products (
            canonical_name,
            status
        )
        VALUES (?, 'needs_review')
    """, (canonical_name,))

    return cursor.lastrowid


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
    Create a raw product observation and its provisional product.

    No product identity is being confirmed here.
    """

    product_id = create_provisional_product(
        master_conn,
        clean_name,
    )

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
            ?, ?, ?, ?, ?, ?, ?, ?, 'unmatched', NULL
        )
    """, (
        receipt_item_id,
        raw_name,
        clean_name,
        price,
        store,
        full_address,
        date,
        product_id,
    ))

    return cursor.lastrowid, product_id


def save_identifier_observations(
    master_conn,
    observation_id,
    raw_name,
    clean_name,
):
    """
    Extract possible identifiers from the receipt item's OCR text.

    These remain observations only. They are not associated with a
    canonical product as part of this function.
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

            # This is identifier extraction/validation confidence.
            # It is NOT product-match confidence.
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


def create_exact_identifier_candidates(master_conn):
    """
    Find observations sharing an exact identifier.

    This creates candidate relationships only.

    No candidate is automatically confirmed.
    """

    cursor = master_conn.cursor()

    cursor.execute("""
        SELECT
            oi1.observation_id,
            po1.product_id,
            oi1.identifier_type,
            oi1.identifier_value,
            oi1.confidence,
            oi2.observation_id,
            po2.product_id,
            oi2.confidence
        FROM observation_identifiers oi1

        JOIN observation_identifiers oi2
            ON oi1.identifier_type = oi2.identifier_type
            AND oi1.identifier_value = oi2.identifier_value
            AND oi1.observation_id < oi2.observation_id

        JOIN product_observations po1
            ON po1.id = oi1.observation_id

        JOIN product_observations po2
            ON po2.id = oi2.observation_id

        WHERE po1.product_id IS NOT NULL
          AND po2.product_id IS NOT NULL
    """)

    matches = cursor.fetchall()

    candidates_created = 0
    evidence_created = 0

    for match in matches:

        (
            observation_id_1,
            product_id_1,
            identifier_type,
            identifier_value,
            confidence_1,
            observation_id_2,
            product_id_2,
            confidence_2,
        ) = match

        # ---------------------------------------------------------
        # Observation 1 -> Product 2
        # ---------------------------------------------------------

        if observation_id_1 != observation_id_2:

            cursor.execute("""
                SELECT id
                FROM match_candidates
                WHERE observation_id = ?
                  AND candidate_product_id = ?
                LIMIT 1
            """, (
                observation_id_1,
                product_id_2,
            ))

            candidate = cursor.fetchone()

            if candidate is None:

                # Exact identifier evidence is currently given a
                # provisional high score. The overall scoring model
                # will be designed later.
                cursor.execute("""
                    INSERT INTO match_candidates (
                        observation_id,
                        candidate_product_id,
                        confidence,
                        status
                    )
                    VALUES (?, ?, ?, 'pending')
                """, (
                    observation_id_1,
                    product_id_2,
                    0.95,
                ))

                candidate_id = cursor.lastrowid

                cursor.execute("""
                    INSERT INTO match_evidence (
                        candidate_id,
                        evidence_type,
                        score,
                        details
                    )
                    VALUES (?, ?, ?, ?)
                """, (
                    candidate_id,
                    "exact_identifier",
                    1.0,
                    (
                        f"Exact {identifier_type} match: "
                        f"{identifier_value}"
                    ),
                ))

                candidates_created += 1
                evidence_created += 1

            else:
                candidate_id = candidate[0]

                cursor.execute("""
                    SELECT 1
                    FROM match_evidence
                    WHERE candidate_id = ?
                      AND evidence_type = 'exact_identifier'
                      AND details = ?
                    LIMIT 1
                """, (
                    candidate_id,
                    f"Exact {identifier_type} match: "
                    f"{identifier_value}",
                ))

                if cursor.fetchone() is None:

                    cursor.execute("""
                        INSERT INTO match_evidence (
                            candidate_id,
                            evidence_type,
                            score,
                            details
                        )
                        VALUES (?, ?, ?, ?)
                    """, (
                        candidate_id,
                        "exact_identifier",
                        1.0,
                        (
                            f"Exact {identifier_type} match: "
                            f"{identifier_value}"
                        ),
                    ))

                    evidence_created += 1

        # ---------------------------------------------------------
        # Observation 2 -> Product 1
        #
        # We also create the reverse candidate so either observation
        # can find the other.
        # ---------------------------------------------------------

        cursor.execute("""
            SELECT id
            FROM match_candidates
            WHERE observation_id = ?
              AND candidate_product_id = ?
            LIMIT 1
        """, (
            observation_id_2,
            product_id_1,
        ))

        candidate = cursor.fetchone()

        if candidate is None:

            cursor.execute("""
                INSERT INTO match_candidates (
                    observation_id,
                    candidate_product_id,
                    confidence,
                    status
                )
                VALUES (?, ?, ?, 'pending')
            """, (
                observation_id_2,
                product_id_1,
                0.95,
            ))

            candidate_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO match_evidence (
                    candidate_id,
                    evidence_type,
                    score,
                    details
                )
                VALUES (?, ?, ?, ?)
            """, (
                candidate_id,
                "exact_identifier",
                1.0,
                (
                    f"Exact {identifier_type} match: "
                    f"{identifier_value}"
                ),
            ))

            candidates_created += 1
            evidence_created += 1

        else:

            candidate_id = candidate[0]

            cursor.execute("""
                SELECT 1
                FROM match_evidence
                WHERE candidate_id = ?
                  AND evidence_type = 'exact_identifier'
                  AND details = ?
                LIMIT 1
            """, (
                candidate_id,
                f"Exact {identifier_type} match: "
                f"{identifier_value}",
            ))

            if cursor.fetchone() is None:

                cursor.execute("""
                    INSERT INTO match_evidence (
                        candidate_id,
                        evidence_type,
                        score,
                        details
                    )
                    VALUES (?, ?, ?, ?)
                """, (
                    candidate_id,
                    "exact_identifier",
                    1.0,
                    (
                        f"Exact {identifier_type} match: "
                        f"{identifier_value}"
                    ),
                ))

                evidence_created += 1

    return candidates_created, evidence_created


def import_observations():
    """
    Import receipt items into master.db and generate exact
    identifier candidates.

    No automatic product merging is performed.
    """

    receipts_conn = connect_database(RECEIPTS_DB)
    master_conn = connect_database(MASTER_DB)

    master_conn.execute("PRAGMA foreign_keys = ON")

    try:

        items = get_receipt_items(receipts_conn)

        imported = 0
        skipped = 0

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

            observation_id, product_id = create_observation(
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

        candidates_created, evidence_created = (
            create_exact_identifier_candidates(master_conn)
        )

        master_conn.commit()

        cursor = master_conn.cursor()

        cursor.execute("""
            SELECT COUNT(*)
            FROM products
        """)

        product_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM product_observations
        """)

        observation_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM observation_identifiers
        """)

        identifier_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*)
            FROM match_candidates
        """)

        candidate_count = cursor.fetchone()[0]

        print("SmartCart comparison pass complete.")
        print("----------------------------------")
        print(f"Receipt items found:       {len(items)}")
        print(f"New observations:          {imported}")
        print(f"Already imported:          {skipped}")
        print(f"Products:                  {product_count}")
        print(f"Observations:              {observation_count}")
        print(f"Identifier observations:   {identifier_count}")
        print(f"New candidates:            {candidates_created}")
        print(f"New evidence records:      {evidence_created}")
        print(f"Total candidates:          {candidate_count}")

    except Exception:
        master_conn.rollback()
        raise

    finally:
        receipts_conn.close()
        master_conn.close()


if __name__ == "__main__":
    import_observations()

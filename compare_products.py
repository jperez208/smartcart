import sqlite3
from pathlib import Path


RECEIPTS_DB = Path("receipts.db")
MASTER_DB = Path("master.db")


# ---------------------------------------------------------
# Identifier evidence weights
# ---------------------------------------------------------

IDENTIFIER_WEIGHTS = {
    "UPC": 0.95,
    "EAN": 0.95,
    "SKU": 0.85,
    "PLU": 0.80,
}


def connect_database(path):
    """Connect to a SQLite database."""
    if not path.exists():
        raise FileNotFoundError(f"Database not found: {path}")

    return sqlite3.connect(path)


# ---------------------------------------------------------
# Identifier classification
# ---------------------------------------------------------

def classify_identifier(identifier_type, identifier_value):
    """
    Interpret an extracted identifier for matching purposes.

    IMPORTANT:
    The original observation_identifiers record is not changed.

    Some grocery produce codes appear in OCR as twelve-digit,
    zero-padded values such as:

        000000004065

    These are treated as PLU-like identifiers for comparison
    purposes rather than being given full UPC strength.
    """

    value = str(identifier_value).strip()

    # Zero-padded four-digit produce code.
    #
    # Example:
    #     000000004065 -> PLU 4065
    #
    if (
        identifier_type == "UPC"
        and len(value) == 12
        and value.startswith("00000000")
        and value[8:].isdigit()
    ):
        return "PLU"

    return identifier_type


def identifier_weight(identifier_type):
    """Return base evidence strength for an identifier type."""
    return IDENTIFIER_WEIGHTS.get(identifier_type, 0.50)


# ---------------------------------------------------------
# Candidate lookup
# ---------------------------------------------------------

def candidate_exists(cursor, observation_id, candidate_product_id):
    """Check whether a candidate relationship already exists."""

    cursor.execute("""
        SELECT id
        FROM match_candidates
        WHERE observation_id = ?
          AND candidate_product_id = ?
        LIMIT 1
    """, (
        observation_id,
        candidate_product_id,
    ))

    row = cursor.fetchone()

    return row[0] if row else None


def evidence_exists(
    cursor,
    candidate_id,
    evidence_type,
    details,
):
    """Check whether identical evidence already exists."""

    cursor.execute("""
        SELECT id
        FROM match_evidence
        WHERE candidate_id = ?
          AND evidence_type = ?
          AND details = ?
        LIMIT 1
    """, (
        candidate_id,
        evidence_type,
        details,
    ))

    return cursor.fetchone() is not None


# ---------------------------------------------------------
# Candidate creation
# ---------------------------------------------------------

def create_candidate(
    cursor,
    observation_id,
    candidate_product_id,
    confidence,
):
    """
    Create a pending candidate if it does not already exist.
    """

    existing_id = candidate_exists(
        cursor,
        observation_id,
        candidate_product_id,
    )

    if existing_id is not None:
        return existing_id, False

    cursor.execute("""
        INSERT INTO match_candidates (
            observation_id,
            candidate_product_id,
            confidence,
            status
        )
        VALUES (?, ?, ?, 'pending')
    """, (
        observation_id,
        candidate_product_id,
        confidence,
    ))

    return cursor.lastrowid, True


def add_evidence(
    cursor,
    candidate_id,
    evidence_type,
    score,
    details,
):
    """
    Add evidence only if that exact evidence does not already exist.
    """

    if evidence_exists(
        cursor,
        candidate_id,
        evidence_type,
        details,
    ):
        return False

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
        evidence_type,
        score,
        details,
    ))

    return True


# ---------------------------------------------------------
# Exact identifier matching
# ---------------------------------------------------------

def get_identifier_matches(master_conn):
    """
    Find observations sharing the same identifier value.

    Raw identifier observations remain unchanged.

    The comparison layer classifies the identifier and determines
    how strong the resulting evidence should be.
    """

    cursor = master_conn.cursor()

    cursor.execute("""
        SELECT
            oi.observation_id,
            oi.identifier_type,
            oi.identifier_value,
            oi.confidence,

            po.product_id,
            po.store

        FROM observation_identifiers oi

        JOIN product_observations po
            ON po.id = oi.observation_id

        WHERE po.product_id IS NOT NULL

        ORDER BY
            oi.identifier_type,
            oi.identifier_value,
            oi.observation_id
    """)

    rows = cursor.fetchall()

    return rows


def build_identifier_groups(rows):
    """
    Group observations by interpreted identifier type and value.

    Example:

        PLU + 000000004065

    becomes one comparison group.
    """

    groups = {}

    for row in rows:

        (
            observation_id,
            identifier_type,
            identifier_value,
            extraction_confidence,
            product_id,
            store,
        ) = row

        interpreted_type = classify_identifier(
            identifier_type,
            identifier_value,
        )

        value = str(identifier_value).strip()

        key = (
            interpreted_type,
            value,
        )

        groups.setdefault(key, []).append({
            "observation_id": observation_id,
            "identifier_type": identifier_type,
            "interpreted_type": interpreted_type,
            "identifier_value": value,
            "extraction_confidence": (
                extraction_confidence
                if extraction_confidence is not None
                else 0.5
            ),
            "product_id": product_id,
            "store": store,
        })

    return groups


# ---------------------------------------------------------
# Confidence calculation
# ---------------------------------------------------------

def calculate_identifier_confidence(
    interpreted_type,
    confidence_1,
    confidence_2,
    same_store,
):
    """
    Calculate provisional candidate confidence.

    This is deliberately conservative.

    It is NOT the final SmartCart scoring algorithm.
    """

    base = identifier_weight(interpreted_type)

    extraction_confidence = (
        float(confidence_1) *
        float(confidence_2)
    )

    confidence = base * extraction_confidence

    # Same store provides supporting context.
    #
    # It is intentionally a small adjustment because the same
    # identifier can theoretically exist across different stores.
    if same_store:
        confidence += 0.03

    return min(confidence, 0.99)


# ---------------------------------------------------------
# Process one candidate direction
# ---------------------------------------------------------

def process_candidate_direction(
    cursor,
    source,
    target,
):
    """
    Create:

        source observation
            ->
        target product

    as a pending candidate.
    """

    same_store = (
        source["store"]
        and target["store"]
        and source["store"].strip().lower()
        == target["store"].strip().lower()
    )

    confidence = calculate_identifier_confidence(
        interpreted_type=source["interpreted_type"],
        confidence_1=source["extraction_confidence"],
        confidence_2=target["extraction_confidence"],
        same_store=same_store,
    )

    candidate_id, created = create_candidate(
        cursor,
        source["observation_id"],
        target["product_id"],
        confidence,
    )

    evidence_type = "exact_identifier"

    details = (
        f"Exact {source['interpreted_type']} match: "
        f"{source['identifier_value']}"
    )

    evidence_added = add_evidence(
        cursor,
        candidate_id,
        evidence_type,
        identifier_weight(source["interpreted_type"]),
        details,
    )

    # Add extraction-confidence evidence separately.
    extraction_details = (
        f"Identifier extraction confidence: "
        f"{source['extraction_confidence']:.2f} / "
        f"{target['extraction_confidence']:.2f}"
    )

    extraction_added = add_evidence(
        cursor,
        candidate_id,
        "identifier_extraction_confidence",
        (
            float(source["extraction_confidence"]) *
            float(target["extraction_confidence"])
        ),
        extraction_details,
    )

    if same_store:

        store_details = (
            f"Same store: {source['store']}"
        )

        store_added = add_evidence(
            cursor,
            candidate_id,
            "same_store",
            0.03,
            store_details,
        )

    else:
        store_added = False

    return (
        created,
        evidence_added,
        extraction_added,
        store_added,
    )


# ---------------------------------------------------------
# Generate candidates
# ---------------------------------------------------------

def create_exact_identifier_candidates(master_conn):
    """
    Generate conservative candidates from exact identifier matches.

    No products are merged.
    No candidate is confirmed.
    """

    rows = get_identifier_matches(master_conn)

    groups = build_identifier_groups(rows)

    cursor = master_conn.cursor()

    candidates_created = 0
    evidence_created = 0

    for (
        interpreted_type,
        identifier_value,
    ), observations in groups.items():

        # Ignore identifiers seen only once.
        if len(observations) < 2:
            continue

        # Compare every observation against the others.
        #
        # This intentionally produces directional candidates:
        #
        # observation A -> product B
        # observation B -> product A
        #
        # because later a product may absorb multiple observations.
        for index, source in enumerate(observations):

            for target_index, target in enumerate(observations):

                if index == target_index:
                    continue

                (
                    candidate_created,
                    evidence_added,
                    extraction_added,
                    store_added,
                ) = process_candidate_direction(
                    cursor,
                    source,
                    target,
                )

                if candidate_created:
                    candidates_created += 1

                evidence_created += sum([
                    evidence_added,
                    extraction_added,
                    store_added,
                ])

    return candidates_created, evidence_created


# ---------------------------------------------------------
# Main comparison pass
# ---------------------------------------------------------

def run_comparison():
    """
    Run the current SmartCart comparison pass.

    This pass only uses exact identifier observations.

    It does not:
        - merge products
        - confirm products
        - use external databases
        - perform fuzzy name matching
    """

    master_conn = connect_database(MASTER_DB)

    master_conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    try:

        candidates_created, evidence_created = (
            create_exact_identifier_candidates(
                master_conn
            )
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

        cursor.execute("""
            SELECT COUNT(*)
            FROM match_evidence
        """)

        evidence_count = cursor.fetchone()[0]

        print("SmartCart comparison pass complete.")
        print("----------------------------------")
        print(f"Products:                  {product_count}")
        print(f"Observations:              {observation_count}")
        print(f"Identifier observations:   {identifier_count}")
        print(f"New candidates:            {candidates_created}")
        print(f"New evidence:              {evidence_created}")
        print(f"Total candidates:          {candidate_count}")
        print(f"Total evidence:            {evidence_count}")
        print()
        print("No products were merged.")
        print("No candidates were confirmed.")

    except Exception:
        master_conn.rollback()
        raise

    finally:
        master_conn.close()


if __name__ == "__main__":
    run_comparison()

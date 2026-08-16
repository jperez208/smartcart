import sqlite3
from pathlib import Path


MASTER_DB = Path("master.db")


# ---------------------------------------------------------------------------
# Identifier evidence weights
# ---------------------------------------------------------------------------

IDENTIFIER_WEIGHTS = {
    "UPC": 0.95,
    "EAN": 0.95,
    "SKU": 0.85,
    "PLU": 0.80,
}


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def connect_database(path):
    if not path.exists():
        raise FileNotFoundError(
            f"Database not found: {path}"
        )

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    return conn


# ---------------------------------------------------------------------------
# Identifier classification
# ---------------------------------------------------------------------------

def classify_identifier(identifier_type, identifier_value):
    """
    Interpret an OCR identifier for comparison purposes.

    Example:

        UPC 000000004065

    is treated as PLU 4065 for matching purposes.
    """

    value = str(identifier_value).strip()

    if (
        identifier_type == "UPC"
        and len(value) == 12
        and value.startswith("00000000")
        and value[8:].isdigit()
    ):
        return "PLU"

    return identifier_type


def identifier_weight(identifier_type):
    return IDENTIFIER_WEIGHTS.get(
        identifier_type,
        0.50,
    )


# ---------------------------------------------------------------------------
# Load identifier observations
# ---------------------------------------------------------------------------

def get_identifier_observations(master_conn):
    """
    Return identifier observations.

    IMPORTANT:

    There is intentionally NO requirement for product_id.

    At this stage observations are compared against other observations.
    """

    cursor = master_conn.cursor()

    cursor.execute(
        """
        SELECT
            oi.observation_id,
            oi.identifier_type,
            oi.identifier_value,
            oi.confidence,

            po.raw_name,
            po.clean_name,
            po.price,
            po.store,
            po.full_address,
            po.date

        FROM observation_identifiers oi

        JOIN product_observations po
            ON po.id = oi.observation_id

        ORDER BY
            oi.identifier_type,
            oi.identifier_value,
            oi.observation_id
        """
    )

    return cursor.fetchall()


# ---------------------------------------------------------------------------
# Group observations by identifier
# ---------------------------------------------------------------------------

def build_identifier_groups(rows):
    """
    Group observations sharing the same interpreted identifier.
    """

    groups = {}

    for row in rows:

        interpreted_type = classify_identifier(
            row["identifier_type"],
            row["identifier_value"],
        )

        value = str(
            row["identifier_value"]
        ).strip()

        key = (
            interpreted_type,
            value,
        )

        groups.setdefault(
            key,
            [],
        ).append(
            {
                "observation_id": row["observation_id"],
                "identifier_type": row["identifier_type"],
                "interpreted_type": interpreted_type,
                "identifier_value": value,
                "extraction_confidence": (
                    row["confidence"]
                    if row["confidence"] is not None
                    else 0.50
                ),
                "raw_name": row["raw_name"],
                "clean_name": row["clean_name"],
                "price": row["price"],
                "store": row["store"],
                "full_address": row["full_address"],
                "date": row["date"],
            }
        )

    return groups


# ---------------------------------------------------------------------------
# Candidate lookup
# ---------------------------------------------------------------------------

def candidate_exists(
    cursor,
    observation_id,
    candidate_product_id,
):
    """
    Kept for compatibility with the existing schema.

    Product candidates are NOT created yet because products do not exist
    at this stage.
    """

    cursor.execute(
        """
        SELECT id
        FROM match_candidates
        WHERE observation_id = ?
          AND candidate_product_id = ?
        LIMIT 1
        """,
        (
            observation_id,
            candidate_product_id,
        ),
    )

    row = cursor.fetchone()

    return row[0] if row else None


# ---------------------------------------------------------------------------
# Evidence helpers
# ---------------------------------------------------------------------------

def evidence_exists(
    cursor,
    candidate_id,
    evidence_type,
    details,
):
    cursor.execute(
        """
        SELECT id
        FROM match_evidence
        WHERE candidate_id = ?
          AND evidence_type = ?
          AND details = ?
        LIMIT 1
        """,
        (
            candidate_id,
            evidence_type,
            details,
        ),
    )

    return cursor.fetchone() is not None


# ---------------------------------------------------------------------------
# Observation-pair table
#
# The existing schema does not currently have a table for observation-to-
# observation candidates.
#
# We create one here rather than misusing match_candidates.
# ---------------------------------------------------------------------------

def ensure_observation_matches_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS observation_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            observation_id_a INTEGER NOT NULL,
            observation_id_b INTEGER NOT NULL,

            confidence REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',

            created_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reviewed_date TEXT,

            FOREIGN KEY (observation_id_a)
                REFERENCES product_observations(id)
                ON DELETE CASCADE,

            FOREIGN KEY (observation_id_b)
                REFERENCES product_observations(id)
                ON DELETE CASCADE,

            UNIQUE (
                observation_id_a,
                observation_id_b
            )
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS observation_match_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            match_id INTEGER NOT NULL,

            evidence_type TEXT NOT NULL,
            score REAL,
            details TEXT,

            created_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (match_id)
                REFERENCES observation_matches(id)
                ON DELETE CASCADE
        )
        """
    )


# ---------------------------------------------------------------------------
# Observation match creation
# ---------------------------------------------------------------------------

def observation_match_exists(
    cursor,
    observation_a,
    observation_b,
):
    cursor.execute(
        """
        SELECT id
        FROM observation_matches
        WHERE observation_id_a = ?
          AND observation_id_b = ?
        LIMIT 1
        """,
        (
            observation_a,
            observation_b,
        ),
    )

    row = cursor.fetchone()

    return row[0] if row else None


def create_observation_match(
    cursor,
    observation_a,
    observation_b,
    confidence,
):
    existing_id = observation_match_exists(
        cursor,
        observation_a,
        observation_b,
    )

    if existing_id is not None:
        return existing_id, False

    cursor.execute(
        """
        INSERT INTO observation_matches (
            observation_id_a,
            observation_id_b,
            confidence,
            status
        )
        VALUES (?, ?, ?, 'pending')
        """,
        (
            observation_a,
            observation_b,
            confidence,
        ),
    )

    return cursor.lastrowid, True


def add_observation_evidence(
    cursor,
    match_id,
    evidence_type,
    score,
    details,
):
    if evidence_exists(
        cursor,
        match_id,
        evidence_type,
        details,
    ):
        return False

    cursor.execute(
        """
        INSERT INTO observation_match_evidence (
            match_id,
            evidence_type,
            score,
            details
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            match_id,
            evidence_type,
            score,
            details,
        ),
    )

    return True


# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------

def calculate_identifier_confidence(
    identifier_type,
    confidence_a,
    confidence_b,
    same_store,
):
    base = identifier_weight(
        identifier_type
    )

    extraction_confidence = (
        float(confidence_a)
        * float(confidence_b)
    )

    confidence = (
        base
        * extraction_confidence
    )

    if same_store:
        confidence += 0.03

    return min(
        confidence,
        0.99,
    )


# ---------------------------------------------------------------------------
# Process one observation pair
# ---------------------------------------------------------------------------

def process_observation_pair(
    cursor,
    source,
    target,
):
    same_store = (
        source["store"]
        and target["store"]
        and source["store"].strip().lower()
        == target["store"].strip().lower()
    )

    confidence = calculate_identifier_confidence(
        identifier_type=source["interpreted_type"],
        confidence_a=source["extraction_confidence"],
        confidence_b=target["extraction_confidence"],
        same_store=same_store,
    )

    match_id, created = create_observation_match(
        cursor,
        source["observation_id"],
        target["observation_id"],
        confidence,
    )

    evidence_created = 0

    details = (
        f"Exact {source['interpreted_type']} match: "
        f"{source['identifier_value']}"
    )

    if add_observation_evidence(
        cursor,
        match_id,
        "exact_identifier",
        identifier_weight(
            source["interpreted_type"]
        ),
        details,
    ):
        evidence_created += 1

    extraction_details = (
        "Identifier extraction confidence: "
        f"{source['extraction_confidence']:.2f} / "
        f"{target['extraction_confidence']:.2f}"
    )

    if add_observation_evidence(
        cursor,
        match_id,
        "identifier_extraction_confidence",
        (
            float(
                source["extraction_confidence"]
            )
            *
            float(
                target["extraction_confidence"]
            )
        ),
        extraction_details,
    ):
        evidence_created += 1

    if same_store:

        store_details = (
            f"Same store: {source['store']}"
        )

        if add_observation_evidence(
            cursor,
            match_id,
            "same_store",
            0.03,
            store_details,
        ):
            evidence_created += 1

    return created, evidence_created


# ---------------------------------------------------------------------------
# Generate exact identifier observation matches
# ---------------------------------------------------------------------------

def create_exact_identifier_matches(master_conn):
    rows = get_identifier_observations(
        master_conn
    )

    groups = build_identifier_groups(
        rows
    )

    cursor = master_conn.cursor()

    matches_created = 0
    evidence_created = 0

    for (
        interpreted_type,
        identifier_value,
    ), observations in groups.items():

        if len(observations) < 2:
            continue

        for index, source in enumerate(
            observations
        ):

            for target_index, target in enumerate(
                observations
            ):

                if index == target_index:
                    continue

                (
                    match_created,
                    evidence_count,
                ) = process_observation_pair(
                    cursor,
                    source,
                    target,
                )

                if match_created:
                    matches_created += 1

                evidence_created += (
                    evidence_count
                )

    return (
        matches_created,
        evidence_created,
    )

# ---------------------------------------------------------------------------
# Create master products from strong exact-identifier groups
# ---------------------------------------------------------------------------

MASTER_IDENTIFIER_TYPES = {
    "UPC",
    "EAN",
    "SKU",
}


def get_master_identifier_groups(master_conn):
    """
    Return observations grouped by strong identifiers.

    PLU is intentionally excluded for now because PLUs can represent
    generic products such as produce rather than a unique packaged product.
    """

    rows = get_identifier_observations(
        master_conn
    )

    groups = {}

    for row in rows:

        interpreted_type = classify_identifier(
            row["identifier_type"],
            row["identifier_value"],
        )

        if interpreted_type not in MASTER_IDENTIFIER_TYPES:
            continue

        value = str(
            row["identifier_value"]
        ).strip()

        key = (
            interpreted_type,
            value,
        )

        groups.setdefault(
            key,
            [],
        ).append(row)

    return groups


def create_master_product(
    cursor,
    observations,
):
    """
    Create one master product from a group of observations sharing
    the same strong identifier.

    The most common clean_name becomes the initial canonical name.
    """

    names = []

    for observation in observations:

        name = observation["clean_name"]

        if name:
            name = str(name).strip()

            if name:
                names.append(name)

    if not names:
        canonical_name = "Unknown product"
    else:
        counts = {}

        for name in names:
            counts[name] = (
                counts.get(name, 0) + 1
            )

        canonical_name = max(
            counts,
            key=counts.get,
        )

    cursor.execute(
        """
        INSERT INTO products (
            canonical_name,
            status
        )
        VALUES (?, 'needs_review')
        """,
        (
            canonical_name,
        ),
    )

    return cursor.lastrowid


def add_product_identifier(
    cursor,
    product_id,
    identifier_type,
    identifier_value,
    confidence,
):
    """
    Add the strong identifier to the master product.
    """

    cursor.execute(
        """
        INSERT OR IGNORE INTO identifiers (
            product_id,
            identifier_type,
            identifier_value,
            confidence
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            product_id,
            identifier_type,
            identifier_value,
            confidence,
        ),
    )


def add_product_name(
    cursor,
    product_id,
    observed_name,
):
    """
    Record an observed name associated with the master product.
    """

    if not observed_name:
        return

    observed_name = str(
        observed_name
    ).strip()

    if not observed_name:
        return

    cursor.execute(
        """
        INSERT INTO product_names (
            product_id,
            observed_name,
            normalized_name
        )
        VALUES (?, ?, ?)

        ON CONFLICT (
            product_id,
            observed_name
        )
        DO UPDATE SET
            occurrence_count =
                occurrence_count + 1,
            last_seen =
                CURRENT_TIMESTAMP
        """,
        (
            product_id,
            observed_name,
            observed_name.upper(),
        ),
    )


def assign_observation_to_product(
    cursor,
    observation_id,
    product_id,
    confidence,
):
    """
    Assign an observation to a master product.
    """

    cursor.execute(
        """
        UPDATE product_observations
        SET
            product_id = ?,
            match_status = 'matched',
            confidence = ?
        WHERE id = ?
          AND (
              product_id IS NULL
              OR product_id = ?
          )
        """,
        (
            product_id,
            confidence,
            observation_id,
            product_id,
        ),
    )


def build_master_products(
    master_conn,
):
    """
    Create master products from strong exact identifiers.

    Only UPC, EAN, and SKU are used at this stage.

    Existing assignments are preserved.
    """

    groups = get_master_identifier_groups(
        master_conn
    )

    cursor = master_conn.cursor()

    products_created = 0
    observations_assigned = 0
    identifiers_added = 0
    names_added = 0

    for (
        identifier_type,
        identifier_value,
    ), observations in groups.items():

        # A master product requires the identifier to have appeared
        # on at least two observations.
        if len(observations) < 2:
            continue

        # Find any existing product assignments in this group.
        existing_products = set()

        for observation in observations:

            cursor.execute(
                """
                SELECT product_id
                FROM product_observations
                WHERE id = ?
                """,
                (
                    observation["observation_id"],
                ),
            )

            row = cursor.fetchone()

            if row and row[0] is not None:
                existing_products.add(
                    row[0]
                )

        # If observations in the same exact-identifier group have already
        # been assigned to different products, do not merge them automatically.
        if len(existing_products) > 1:
            continue

        if existing_products:

            product_id = next(
                iter(existing_products)
            )

        else:

            product_id = create_master_product(
                cursor,
                observations,
            )

            products_created += 1

        # Add the strong identifier to the master product.
        confidence_values = [
            observation["confidence"]
            for observation in observations
            if observation["confidence"] is not None
        ]

        if confidence_values:
            identifier_confidence = max(
                confidence_values
            )
        else:
            identifier_confidence = 1.0

        before = cursor.rowcount

        add_product_identifier(
            cursor,
            product_id,
            identifier_type,
            identifier_value,
            identifier_confidence,
        )

        # sqlite rowcount tells us whether INSERT OR IGNORE inserted.
        if cursor.rowcount:
            identifiers_added += 1

        # Assign observations and record their names.
        for observation in observations:

            observation_id = (
                observation["observation_id"]
            )

            cursor.execute(
                """
                SELECT product_id
                FROM product_observations
                WHERE id = ?
                """,
                (
                    observation_id,
                ),
            )

            current = cursor.fetchone()

            if current and current[0] is not None:
                if current[0] != product_id:
                    continue

                # Already assigned.
                add_product_name(
                    cursor,
                    product_id,
                    observation["clean_name"],
                )

                continue

            assign_observation_to_product(
                cursor,
                observation_id,
                product_id,
                identifier_confidence,
            )

            if cursor.rowcount:
                observations_assigned += 1

            add_product_name(
                cursor,
                product_id,
                observation["clean_name"],
            )

            names_added += 1

    return (
        products_created,
        observations_assigned,
        identifiers_added,
        names_added,
    )

# ---------------------------------------------------------------------------
# Main comparison pass
# ---------------------------------------------------------------------------

def run_comparison():

    print()
    print(
        "SmartCart observation comparison pass"
    )
    print(
        "--------------------------------------"
    )

    master_conn = connect_database(
        MASTER_DB
    )

    master_conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    try:

        ensure_observation_matches_table(
            master_conn
        )

        (
            matches_created,
            evidence_created,
        ) = create_exact_identifier_matches(
            master_conn
        )

        (
            products_created,
            observations_assigned,
            identifiers_added,
            names_added,
        ) = build_master_products(
            master_conn
        )

        master_conn.commit()

        cursor = master_conn.cursor()

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM product_observations
            """
        )

        observation_count = (
            cursor.fetchone()[0]
        )

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM observation_identifiers
            """
        )

        identifier_count = (
            cursor.fetchone()[0]
        )

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM observation_matches
            """
        )

        match_count = (
            cursor.fetchone()[0]
        )

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM observation_match_evidence
            """
        )

        evidence_count = (
            cursor.fetchone()[0]
        )

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM products
            """
        )

        product_count = (
            cursor.fetchone()[0]
        )

        print()
        print(
            "Comparison complete."
        )
        print(
            "--------------------"
        )
        print(
            f"Observations:              "
            f"{observation_count}"
        )
        print(
            f"Identifier observations:   "
            f"{identifier_count}"
        )
        print(
            f"New observation matches:   "
            f"{matches_created}"
        )
        print(
            f"New evidence:              "
            f"{evidence_created}"
        )
        print(
            f"Total observation matches:"
            f" {match_count}"
        )
        print(
            f"Total match evidence:      "
            f"{evidence_count}"
        )
                print(
            f"Master products:            "
            f"{product_count}"
        )
        print(
            f"New master products:        "
            f"{products_created}"
        )
        print(
            f"Observations assigned:      "
            f"{observations_assigned}"
        )
        print(
            f"Identifiers added:          "
            f"{identifiers_added}"
        )
        print(
            f"Product names added:        "
            f"{names_added}"
        )
        print()

        if products_created:
            print(
                "Strong exact-identifier products "
                "were created."
            )
        else:
            print(
                "No new master products were created."
            )

        print(
            "Fuzzy name matching is still disabled."
        )
        print(
            "PLU-based master grouping is still disabled."
        )

    except Exception:

        master_conn.rollback()

        raise

    finally:

        master_conn.close()


if __name__ == "__main__":
    run_comparison()

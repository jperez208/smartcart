import sqlite3
from pathlib import Path


MASTER_DB = Path("master.db")


def create_master_db():
    conn = sqlite3.connect(MASTER_DB)
    cursor = conn.cursor()

    # ---------------------------------------------------------
    # Canonical products
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_name TEXT,
            brand TEXT,
            size TEXT,
            status TEXT NOT NULL DEFAULT 'needs_review',
            created_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ---------------------------------------------------------
    # Individual observations imported from receipts.db
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_item_id INTEGER NOT NULL,
            product_id INTEGER,
            match_status TEXT NOT NULL DEFAULT 'unmatched',
            confidence REAL,
            created_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (product_id)
                REFERENCES products(id)
        )
    """)

    # ---------------------------------------------------------
    # Names observed for canonical products
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_names (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            observed_name TEXT NOT NULL,
            normalized_name TEXT,
            occurrence_count INTEGER NOT NULL DEFAULT 1,
            first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (product_id)
                REFERENCES products(id)
        )
    """)

    # ---------------------------------------------------------
    # UPC / EAN / PLU / SKU identifiers
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS identifiers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            identifier_type TEXT NOT NULL,
            identifier_value TEXT NOT NULL,
            confidence REAL,
            occurrence_count INTEGER NOT NULL DEFAULT 1,
            first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (product_id)
                REFERENCES products(id)
        )
    """)

    # ---------------------------------------------------------
    # Store chains/names
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_name TEXT NOT NULL,
            normalized_name TEXT,
            created_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ---------------------------------------------------------
    # Individual store locations
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id INTEGER NOT NULL,
            address TEXT,
            normalized_address TEXT,
            first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (store_id)
                REFERENCES stores(id)
        )
    """)

    # ---------------------------------------------------------
    # Possible matches waiting for confirmation
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS match_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observation_id INTEGER NOT NULL,
            candidate_product_id INTEGER NOT NULL,
            confidence REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            reviewed_date TEXT,

            FOREIGN KEY (observation_id)
                REFERENCES product_observations(id),

            FOREIGN KEY (candidate_product_id)
                REFERENCES products(id)
        )
    """)

    # ---------------------------------------------------------
    # Evidence explaining candidate matches
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS match_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            evidence_type TEXT NOT NULL,
            score REAL,
            details TEXT,
            created_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (candidate_id)
                REFERENCES match_candidates(id)
        )
    """)

    # ---------------------------------------------------------
    # History of changes to canonical products
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            reason TEXT,
            created_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (product_id)
                REFERENCES products(id)
        )
    """)

    # ---------------------------------------------------------
    # Indexes
    # ---------------------------------------------------------

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_observations_receipt_item
        ON product_observations(receipt_item_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_observations_product
        ON product_observations(product_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_observations_status
        ON product_observations(match_status)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_product_names_product
        ON product_names(product_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_product_names_normalized
        ON product_names(normalized_name)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_identifiers_product
        ON identifiers(product_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_identifiers_value
        ON identifiers(identifier_type, identifier_value)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_candidates_observation
        ON match_candidates(observation_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_candidates_product
        ON match_candidates(candidate_product_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_candidates_status
        ON match_candidates(status)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_evidence_candidate
        ON match_evidence(candidate_id)
    """)

    conn.commit()
    conn.close()

    print(f"master.db created successfully: {MASTER_DB.resolve()}")


if __name__ == "__main__":
    create_master_db()

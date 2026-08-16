import sqlite3
from pathlib import Path


MASTER_DB = Path("master.db")


def create_master_db():
    conn = sqlite3.connect(MASTER_DB)

    # SQLite foreign-key enforcement must be enabled per connection.
    conn.execute("PRAGMA foreign_keys = ON")

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
    #
    # This table represents what was actually observed on a
    # receipt. It does NOT represent SmartCart's conclusion
    # about what the product is.
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            receipt_item_id INTEGER NOT NULL UNIQUE,

            raw_name TEXT,
            clean_name TEXT,
            price REAL,
            store TEXT,
            full_address TEXT,
            date TEXT,

            product_id INTEGER,

            match_status TEXT NOT NULL DEFAULT 'unmatched',
            confidence REAL,

            created_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (product_id)
                REFERENCES products(id)
        )
    """)

    # ---------------------------------------------------------
    # Identifier observations extracted from receipt items
    #
    # These are raw/learned observations and do NOT require
    # a canonical product assignment.
    # ---------------------------------------------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS observation_identifiers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            observation_id INTEGER NOT NULL,
            identifier_type TEXT NOT NULL,
            identifier_value TEXT NOT NULL,
            confidence REAL,

            created_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (observation_id)
                REFERENCES product_observations(id)
                ON DELETE CASCADE,

            UNIQUE (
                observation_id,
                identifier_type,
                identifier_value
            )
        )
    """)

    # ---------------------------------------------------------
    # Names observed for canonical products
    #
    # These are learned aliases/variants after an observation
    # has been associated with a canonical product.
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
                ON DELETE CASCADE,

            UNIQUE (
                product_id,
                observed_name
            )
        )
    """)

    # ---------------------------------------------------------
    # Confirmed identifiers associated with canonical products
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
                ON DELETE CASCADE,

            UNIQUE (
                product_id,
                identifier_type,
                identifier_value
            )
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

            created_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (normalized_name)
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
                ON DELETE CASCADE,

            UNIQUE (
                store_id,
                normalized_address
            )
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
                REFERENCES product_observations(id)
                ON DELETE CASCADE,

            FOREIGN KEY (candidate_product_id)
                REFERENCES products(id)
                ON DELETE CASCADE,

            UNIQUE (
                observation_id,
                candidate_product_id
            )
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
                ON DELETE CASCADE
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
                ON DELETE CASCADE
        )
    """)

    # ---------------------------------------------------------
    # Indexes
    # ---------------------------------------------------------

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_observations_product
        ON product_observations(product_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_observations_status
        ON product_observations(match_status)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_observation_identifiers_observation
        ON observation_identifiers(observation_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_observation_identifiers_value
        ON observation_identifiers(identifier_type, identifier_value)
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
        CREATE INDEX IF NOT EXISTS idx_store_locations_store
        ON store_locations(store_id)
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

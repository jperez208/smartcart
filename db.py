import sqlite3

DATABASE = "receipts.db"

def get_connection():
    return sqlite3.connect(DATABASE)

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        store TEXT,
        full_address TEXT,
        date TEXT,
        raw_name TEXT,
        clean_name TEXT,
        price REAL
    )
    """)

    cur.execute("""
    CREATE UNIQUE INDEX IF NOT EXISTS idx_items
    ON items(store, full_address, date, clean_name, price)
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS processed_files(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE,
            file_hash TEXT UNIQUE,
            processed_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
    
    conn.commit()
    conn.close()

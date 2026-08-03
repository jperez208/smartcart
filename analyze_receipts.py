import sqlite3
import pandas as pd
from collections import Counter

DB_PATH = "receipts.db"

def run_analysis():
    try:
        conn = sqlite3.connect(DB_PATH)
    except sqlite3.OperationalError:
        print(f"[Error] Could not find or open database at: {DB_PATH}")
        return

    # 1. Fetch raw transaction records to analyze into a Pandas DataFrame
    query = "SELECT store, full_address, date, raw_name, clean_name, price FROM items"
    try:
        df = pd.read_sql_query(query, conn)
    except pd.errors.DatabaseError:
        print("[Error] Table 'items' does not exist or schema is mismatched.")
        conn.close()
        return

    if df.empty:
        print("Database table 'items' contains no records to analyze yet.")
        conn.close()
        return

    print("\n" + "="*40)
    print("        RECEIPT ANALYSIS REPORT        ")
    print("="*40)

    # 2. General High-Level Financial Analysis
    total_spend = df['price'].sum()
    total_items = len(df)
    avg_item_price = df['price'].mean()
    
    print(f"Total Combined Spend:  ${total_spend:,.2f}")
    print(f"Total Unique Line Items: {total_items}")
    print(f"Average Price Per Item: ${avg_item_price:.2f}")

    # 3. Analyze Outflow Volume by Merchant
    print("\n--- Outflow Volume by Merchant ---")
    store_spending = df.groupby('store')['price'].agg(['sum', 'count']).rename(columns={'sum': 'Spend', 'count': 'Items'})
    store_spending = store_spending.sort_values(by='Spend', ascending=False)
    for store, row in store_spending.iterrows():
        print(f" * {store:<18} | Spend: ${row['Spend']:>7,.2f} ({int(row['Items'])} items)")

    # 4. Analyze Item Frequency Density
    print("\n--- Most Frequently Purchased Items ---")
    item_counts = Counter(df['clean_name'].str.lower())
    for item, count in item_counts.most_common(5):
        print(f" * {item.title():<18} | Count: {count}x")

    # 5. Analyze and Identify Highest Single Expenses
    print("\n--- Top 3 Highest Single Expenses ---")
    top_expensive = df.sort_values(by='price', ascending=False).head(3)
    for _, row in top_expensive.iterrows():
        print(f" * ${row['price']:>6.2f} -> {row['clean_name']} ({row['store']})")

    conn.close()

if __name__ == "__main__":
    run_analysis()

"""
InsightIQ Database & Ingestion Module
Handles SQLite schema creation, data cleaning, validation, audit logging,
and deterministic revenue column calculation.
"""

import os
import sqlite3
import pandas as pd
from typing import Dict, Any, Tuple, Optional

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "insightiq.db")
DEFAULT_CSV_PATH = os.path.join(os.path.dirname(__file__), "data", "sales_data.csv")


def get_db_connection(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Creates a thread-safe connection to the SQLite database with Row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str = DEFAULT_DB_PATH, csv_path: str = DEFAULT_CSV_PATH, force: bool = False) -> Dict[str, Any]:
    """
    Initializes the SQLite schema and ingests sales data from CSV.
    If force is False and data already exists, returns existing audit summary.
    """
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    if force:
        cursor.execute("DROP TABLE IF EXISTS sales_transactions;")
        cursor.execute("DROP TABLE IF EXISTS data_quality_log;")
        cursor.execute("DROP TABLE IF EXISTS ingestion_meta;")

    # Create tables
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sales_transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id TEXT UNIQUE NOT NULL,
        order_date TEXT NOT NULL,
        product TEXT NOT NULL,
        category TEXT NOT NULL,
        region TEXT NOT NULL,
        sales_channel TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        unit_price REAL,
        discount_amount REAL NOT NULL DEFAULT 0.0,
        status TEXT NOT NULL,
        calculated_revenue REAL,
        is_valid_completed INTEGER NOT NULL DEFAULT 0,
        flag_reasons TEXT
    );
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_order_date ON sales_transactions(order_date);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_product ON sales_transactions(product);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_region ON sales_transactions(region);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON sales_transactions(status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_valid_completed ON sales_transactions(is_valid_completed);")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS data_quality_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id TEXT,
        issue_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        description TEXT NOT NULL,
        raw_data TEXT
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ingestion_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)

    conn.commit()

    # Check if table already populated
    cursor.execute("SELECT COUNT(*) FROM sales_transactions;")
    row_count = cursor.fetchone()[0]
    if row_count > 0 and not force:
        conn.close()
        return get_data_quality_summary(db_path)

    # Ingest CSV
    if not os.path.exists(csv_path):
        conn.close()
        raise FileNotFoundError(f"Source sales CSV not found at {csv_path}")

    df_raw = pd.read_csv(csv_path)
    total_raw_rows = len(df_raw)

    valid_rows = 0
    excluded_rows = 0
    flagged_rows = 0
    quality_issues = []
    seen_txn_ids = set()

    for _, row in df_raw.iterrows():
        txn_id = str(row["Transaction_Id"]).strip()
        raw_date = str(row["Order_date"]).strip()
        product = str(row["Product"]).strip()
        category = str(row["Category"]).strip()
        region = str(row["Region"]).strip()
        sales_channel = str(row["Sales_channel"]).strip()
        status = str(row["Status"]).strip()

        # Check for duplicate Transaction IDs
        if txn_id in seen_txn_ids:
            excluded_rows += 1
            quality_issues.append((
                txn_id,
                "DUPLICATE_TRANSACTION_ID",
                "EXCLUSION",
                f"Duplicate transaction ID {txn_id} detected. Skipped to prevent double counting.",
                str(row.to_dict())
            ))
            continue
        seen_txn_ids.add(txn_id)

        # Parse quantity
        try:
            quantity = int(row["Quantity"])
        except (ValueError, TypeError):
            quantity = 0

        # Parse unit price
        raw_price = row["Unit_price"]
        unit_price: Optional[float] = None
        if pd.notnull(raw_price) and str(raw_price).strip() != "":
            try:
                unit_price = float(raw_price)
            except (ValueError, TypeError):
                unit_price = None

        # Parse discount
        try:
            discount_amount = float(row.get("Discount_amount", 0.0))
        except (ValueError, TypeError):
            discount_amount = 0.0

        # Parse date to ISO format YYYY-MM-DD
        parsed_date: Optional[str] = None
        try:
            parsed_date = pd.to_datetime(raw_date, format="%d-%m-%Y").strftime("%Y-%m-%d")
        except Exception:
            try:
                parsed_date = pd.to_datetime(raw_date).strftime("%Y-%m-%d")
            except Exception:
                parsed_date = None

        # Business Logic & Integrity Evaluation
        flags = []
        is_valid_completed = 1
        calculated_revenue: Optional[float] = None

        # Invalid date handling
        if not parsed_date:
            is_valid_completed = 0
            flags.append("INVALID_DATE")
            quality_issues.append((
                txn_id,
                "INVALID_DATE",
                "EXCLUSION",
                f"Transaction {txn_id} has invalid or unparseable order date '{raw_date}'.",
                str(row.to_dict())
            ))
            parsed_date = "1970-01-01"  # Fallback for SQL non-null constraint

        # Negative quantity or price handling
        if quantity < 0 or (unit_price is not None and unit_price < 0):
            is_valid_completed = 0
            flags.append("NEGATIVE_VALUE")
            quality_issues.append((
                txn_id,
                "NEGATIVE_VALUE",
                "EXCLUSION",
                f"Transaction {txn_id} has negative quantity ({quantity}) or price ({unit_price}).",
                str(row.to_dict())
            ))

        # 1. Missing unit price
        if unit_price is None:
            is_valid_completed = 0
            flags.append("MISSING_UNIT_PRICE")
            quality_issues.append((
                txn_id,
                "MISSING_UNIT_PRICE",
                "EXCLUSION",
                f"Transaction {txn_id} has missing unit price. Excluded from revenue calculations to prevent fabrication.",
                str(row.to_dict())
            ))

        # 2. Returned transaction
        if status.lower() == "returned":
            is_valid_completed = 0
            flags.append("RETURNED_TRANSACTION")
            quality_issues.append((
                txn_id,
                "RETURNED_TRANSACTION",
                "EXCLUSION",
                f"Transaction {txn_id} was returned. Excluded from net completed revenue.",
                str(row.to_dict())
            ))

        # 3. Zero quantity
        if quantity == 0:
            flags.append("ZERO_QUANTITY")
            quality_issues.append((
                txn_id,
                "ZERO_QUANTITY",
                "WARNING",
                f"Transaction {txn_id} recorded 0 quantity. Evaluated with 0 revenue contribution.",
                str(row.to_dict())
            ))

        # Calculate revenue if valid completed
        if unit_price is not None:
            # Formula: (quantity * unit_price) - discount_amount
            calculated_revenue = max(0.0, (quantity * unit_price) - discount_amount)
        else:
            calculated_revenue = None

        if is_valid_completed == 1:
            valid_rows += 1
        else:
            excluded_rows += 1

        if flags:
            flagged_rows += 1

        flag_str = ",".join(flags) if flags else None

        cursor.execute("""
        INSERT INTO sales_transactions (
            transaction_id, order_date, product, category, region,
            sales_channel, quantity, unit_price, discount_amount,
            status, calculated_revenue, is_valid_completed, flag_reasons
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, (
            txn_id, parsed_date, product, category, region,
            sales_channel, quantity, unit_price, discount_amount,
            status, calculated_revenue, is_valid_completed, flag_str
        ))

    # Insert data quality issues
    cursor.executemany("""
    INSERT INTO data_quality_log (
        transaction_id, issue_type, severity, description, raw_data
    ) VALUES (?, ?, ?, ?, ?);
    """, quality_issues)

    # Ingestion metadata
    meta = [
        ("total_csv_rows", str(total_raw_rows)),
        ("valid_completed_rows", str(valid_rows)),
        ("excluded_rows", str(excluded_rows)),
        ("flagged_rows", str(flagged_rows)),
        ("csv_source", csv_path),
        ("revenue_policy", "Net Completed Revenue = SUM((Quantity * Unit_Price) - Discount_Amount) WHERE Status = 'Completed' AND Unit_Price IS NOT NULL")
    ]
    cursor.executemany("INSERT OR REPLACE INTO ingestion_meta (key, value) VALUES (?, ?);", meta)

    conn.commit()
    conn.close()

    return get_data_quality_summary(db_path)


def get_data_quality_summary(db_path: str = DEFAULT_DB_PATH) -> Dict[str, Any]:
    """Retrieves full audit report and data quality health metrics from SQLite."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM sales_transactions;")
    total_records = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM sales_transactions WHERE is_valid_completed = 1;")
    valid_completed = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM sales_transactions WHERE is_valid_completed = 0;")
    excluded_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM sales_transactions WHERE flag_reasons IS NOT NULL;")
    flagged_count = cursor.fetchone()[0]

    cursor.execute("SELECT status, COUNT(*) FROM sales_transactions GROUP BY status;")
    status_breakdown = {row["status"]: row[1] for row in cursor.fetchall()}

    cursor.execute("SELECT MIN(order_date), MAX(order_date) FROM sales_transactions;")
    min_date, max_date = cursor.fetchone()

    cursor.execute("""
    SELECT transaction_id, issue_type, severity, description
    FROM data_quality_log
    ORDER BY id ASC;
    """)
    issues = [dict(row) for row in cursor.fetchall()]

    cursor.execute("SELECT key, value FROM ingestion_meta;")
    meta_dict = {row["key"]: row["value"] for row in cursor.fetchall()}

    conn.close()

    return {
        "total_records": total_records,
        "valid_completed_records": valid_completed,
        "excluded_records": excluded_count,
        "flagged_records": flagged_count,
        "status_distribution": status_breakdown,
        "date_range": {"min_date": min_date, "max_date": max_date},
        "issues": issues,
        "revenue_policy": meta_dict.get("revenue_policy", "Net Completed Revenue = (Qty * Unit_Price) - Discount"),
        "integrity_score": round((valid_completed / total_records) * 100, 2) if total_records > 0 else 0.0
    }


if __name__ == "__main__":
    summary = init_db(force=True)
    print("Database Initialized Successfully!")
    print(summary)

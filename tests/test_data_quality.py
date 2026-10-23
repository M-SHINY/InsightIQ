"""
Tests for InsightIQ Data Quality and Ingestion Integrity.
Validates missing price exclusion, returned orders, zero quantities, and audit reporting.
"""

import os
import pytest
import sqlite3
from database import init_db, get_data_quality_summary

TEST_DB_PATH = "test_dq_insightiq.db"


@pytest.fixture(scope="module")
def setup_dq_db():
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    init_db(db_path=TEST_DB_PATH, force=True)
    yield TEST_DB_PATH
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


def test_missing_unit_price_exclusion(setup_dq_db):
    """Verify TXN0051 (missing price) is excluded from revenue and flagged in audit log."""
    conn = sqlite3.connect(setup_dq_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sales_transactions WHERE transaction_id = 'TXN0051';")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row["unit_price"] is None
    assert row["is_valid_completed"] == 0
    assert row["calculated_revenue"] is None
    assert "MISSING_UNIT_PRICE" in row["flag_reasons"]


def test_returned_transaction_exclusion(setup_dq_db):
    """Verify TXN0033 (status 'Returned') is excluded from net completed revenue."""
    conn = sqlite3.connect(setup_dq_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sales_transactions WHERE transaction_id = 'TXN0033';")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row["status"] == "Returned"
    assert row["is_valid_completed"] == 0
    assert "RETURNED_TRANSACTION" in row["flag_reasons"]


def test_zero_quantity_handling(setup_dq_db):
    """Verify TXN0034 (quantity = 0) has calculated revenue 0 and is flagged with warning."""
    conn = sqlite3.connect(setup_dq_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sales_transactions WHERE transaction_id = 'TXN0034';")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row["quantity"] == 0
    assert row["calculated_revenue"] == 0.0
    assert "ZERO_QUANTITY" in row["flag_reasons"]


def test_discount_subtraction(setup_dq_db):
    """Verify TXN0004 discount is accurately subtracted from lump sum."""
    # TXN0004: Monitor, Qty 6, Unit Price 9500, Discount 500
    # Expected: (6 * 9500) - 500 = 57000 - 500 = 56500.0
    conn = sqlite3.connect(setup_dq_db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sales_transactions WHERE transaction_id = 'TXN0004';")
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row["quantity"] == 6
    assert row["unit_price"] == 9500.0
    assert row["discount_amount"] == 500.0
    assert row["calculated_revenue"] == 56500.0


def test_data_quality_summary_metrics(setup_dq_db):
    """Verify audit summary report contains all metrics and issue entries."""
    dq = get_data_quality_summary(setup_dq_db)
    assert dq["total_records"] == 51
    assert dq["valid_completed_records"] == 49
    assert dq["excluded_records"] == 2
    assert dq["flagged_records"] == 3
    assert dq["integrity_score"] > 95.0
    assert len(dq["issues"]) >= 3
    # Verify policy text is present
    assert "Net Completed Revenue" in dq["revenue_policy"]


def test_duplicate_and_invalid_date_rejection(tmp_path):
    """Verify ingestion pipeline catches duplicate IDs, invalid dates, and negative numbers."""
    csv_content = """Transaction_Id,Order_date,Product,Category,Region,Sales_channel,Quantity,Unit_price,Discount_amount,Status
TXN100,01-01-2026,Keyboard,Accessories,North,Online,5,100,0,Completed
TXN100,02-01-2026,Keyboard,Accessories,North,Online,5,100,0,Completed
TXN101,invalid-date,Monitor,Electronics,East,Retail,2,500,0,Completed
TXN102,03-01-2026,Desk,Furniture,South,Retail,-4,1000,0,Completed
"""
    custom_csv = tmp_path / "custom_sales.csv"
    custom_csv.write_text(csv_content)
    custom_db = str(tmp_path / "custom.db")

    summary = init_db(db_path=custom_db, csv_path=str(custom_csv), force=True)
    assert summary["total_records"] == 3  # Duplicate TXN100 was skipped
    assert summary["valid_completed_records"] == 1  # Only the first TXN100 is valid
    assert summary["excluded_records"] == 2  # invalid date and negative qty excluded

    issue_types = [i["issue_type"] for i in summary["issues"]]
    assert "DUPLICATE_TRANSACTION_ID" in issue_types
    assert "INVALID_DATE" in issue_types
    assert "NEGATIVE_VALUE" in issue_types

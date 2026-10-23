"""
Unit and integration tests for InsightIQ AnalyticsEngine.
Verifies all 5 analytical calculations, edge cases, zero baselines, ties, and data integrity.
"""

import os
import pytest
import sqlite3
from database import init_db
from analytics import AnalyticsEngine

TEST_DB_PATH = "test_insightiq.db"


@pytest.fixture(scope="module")
def setup_test_db():
    """Initializes a clean test database using the sales CSV."""
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    init_db(db_path=TEST_DB_PATH, force=True)
    yield TEST_DB_PATH

    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)


@pytest.fixture
def engine(setup_test_db):
    return AnalyticsEngine(db_path=setup_test_db)


def test_total_revenue_calculation(engine):
    """Operation A: Verify total net completed revenue, volume, and exclusion handling."""
    res = engine.get_total_revenue()
    assert res["operation"] == "total_revenue"
    # 49 valid completed transactions totaling 1,439,200.00
    assert res["raw_data"]["total_revenue"] == 1439200.0
    assert res["raw_data"]["transaction_count"] == 49
    assert res["primary_metric"] == "1,439,200.00"
    assert len(res["evidence"]) > 0
    assert len(res["insights"]) > 0


def test_highest_revenue_product(engine):
    """Operation B: Verify Monitor is highest-revenue product with ranked breakdown."""
    res = engine.get_highest_revenue_product()
    assert res["operation"] == "highest_revenue_product"
    assert res["primary_metric"] == "Monitor"
    assert res["primary_metric_secondary"] == "473,000.00"
    assert len(res["breakdown"]) == 7
    # Verify rankings are strictly descending
    revenues = [r["total_revenue"] for r in res["breakdown"]]
    assert revenues == sorted(revenues, reverse=True)
    # Check top product revenue
    assert revenues[0] == 473000.0


def test_monthly_revenue_trend(engine):
    """Operation C: Verify monthly chronological revenue, peak month, and MoM calculations."""
    res = engine.get_monthly_revenue_trend()
    assert res["operation"] == "monthly_revenue_trend"
    breakdown = res["breakdown"]
    assert len(breakdown) == 6
    months = [b["month"] for b in breakdown]
    assert months == ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]

    # Peak month May 2026 = 318,500.00
    may_row = next(b for b in breakdown if b["month"] == "2026-05")
    assert may_row["total_revenue"] == 318500.0

    # Verify MoM change between Jan (210,250) and Feb (234,600): +24,350 (+11.58%)
    feb_evidence = next(e for e in res["evidence"] if e["Month"] == "2026-02")
    assert feb_evidence["MoM Change (Amount)"] == "+24,350.00"
    assert feb_evidence["MoM Change (%)"] == "+11.58%"


def test_highest_sales_region(engine):
    """Operation D: Verify South leads in revenue with comprehensive comparison."""
    res = engine.get_highest_sales_region()
    assert res["operation"] == "highest_sales_region"
    assert res["primary_metric"] == "South"
    assert res["primary_metric_secondary"] == "411,200.00"
    assert len(res["breakdown"]) == 4

    # Verify breakdown orders
    south_row = next(r for r in res["breakdown"] if r["region"] == "South")
    assert south_row["total_revenue"] == 411200.0
    assert south_row["total_units"] == 182
    assert south_row["transaction_count"] == 13


def test_compare_months_revenue_valid(engine):
    """Operation E: Verify accurate variance and growth between Feb 2026 and May 2026."""
    res = engine.compare_months_revenue("2026-02", "2026-05")
    assert res["operation"] == "compare_months_revenue"
    # Feb: $234,600.00; May: $318,500.00; Diff: +$83,900.00; +35.76%
    details = res["comparison_details"]
    assert details["month1"]["revenue"] == 234600.0
    assert details["month2"]["revenue"] == 318500.0
    assert details["absolute_difference"] == 83900.0
    assert round(details["percentage_change"], 2) == 35.76
    assert res["primary_metric"] == "+35.76%"


def test_compare_months_revenue_zero_baseline(engine):
    """Edge Case: Zero baseline revenue handled safely without division by zero."""
    res = engine.compare_months_revenue("2025-01", "2026-01")
    assert res["comparison_details"]["month1"]["revenue"] == 0.0
    assert res["comparison_details"]["percentage_change"] is None
    assert "Undefined" in res["primary_metric"]
    assert any("undefined" in w.lower() for w in res["warnings"])


def test_compare_months_revenue_identical_months(engine):
    """Edge Case: Comparing identical months yields 0 diff and 0% change."""
    res = engine.compare_months_revenue("2026-03", "2026-03")
    details = res["comparison_details"]
    assert details["absolute_difference"] == 0.0
    assert details["percentage_change"] == 0.0


def test_sales_summary(engine):
    """Operation: Executive Sales Summary deterministically combining key dimensions."""
    res = engine.get_sales_summary()
    assert res["operation"] == "sales_summary"
    assert res["primary_metric"] == "1,439,200.00"
    assert res["raw_data"]["total_revenue"] == 1439200.0
    assert res["raw_data"]["top_product"] == "Monitor"
    assert res["raw_data"]["top_region"] == "South"
    assert res["raw_data"]["peak_month"] == "2026-05"
    assert res["raw_data"]["transaction_count"] == 49
    assert len(res["evidence"]) == 4
    assert len(res["insights"]) >= 3
    assert len(res["follow_ups"]) >= 3
    # Check that follow-up suggestions include valid questions
    assert any("monthly revenue trend" in f.lower() for f in res["follow_ups"])


def test_sales_summary_empty_database(tmp_path):
    """Edge Case: Executive sales summary on empty database handles 0 records without crashing."""
    empty_db = str(tmp_path / "empty_sales.db")
    init_db(db_path=empty_db, force=True)
    # Clear all rows
    conn = sqlite3.connect(empty_db)
    conn.execute("DELETE FROM sales_transactions;")
    conn.commit()
    conn.close()

    empty_engine = AnalyticsEngine(db_path=empty_db)
    res = empty_engine.get_sales_summary()
    assert res["operation"] == "sales_summary"
    assert res["primary_metric"] == "0.00"
    assert "No completed sales transactions" in res["summary"]
    assert len(res["warnings"]) > 0
    assert len(res["evidence"]) > 0


def test_product_tie_handling(setup_test_db):
    """Edge Case: Ensure ties in top product revenue are reported cleanly."""
    conn = sqlite3.connect(setup_test_db)
    cursor = conn.cursor()
    # Insert two tied dummy products
    cursor.execute("""
    INSERT INTO sales_transactions (
        transaction_id, order_date, product, category, region, sales_channel,
        quantity, unit_price, discount_amount, status, calculated_revenue, is_valid_completed
    ) VALUES
    ('TIETEST1', '2026-01-01', 'Mega Product A', 'Tech', 'North', 'Online', 10, 100000, 0, 'Completed', 1000000.0, 1),
    ('TIETEST2', '2026-01-01', 'Mega Product B', 'Tech', 'North', 'Online', 10, 100000, 0, 'Completed', 1000000.0, 1);
    """)
    conn.commit()
    conn.close()

    engine = AnalyticsEngine(db_path=setup_test_db)
    res = engine.get_highest_revenue_product()
    assert "Tied" in res["summary"] or "Mega Product" in res["summary"]
    assert res["breakdown"][0]["total_revenue"] == res["breakdown"][1]["total_revenue"]

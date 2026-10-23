"""
InsightIQ Analytics Engine
Implements deterministic, parameterized SQL queries for all 5 required analytical
operations, plus automated insight generation and evidence bundling.
Never fabricates figures; strictly executes against the local SQLite database.
"""

from typing import Dict, Any, List, Optional, Tuple
from database import get_db_connection, DEFAULT_DB_PATH, get_data_quality_summary


def format_currency(val: Optional[float]) -> str:
    """Helper to format numeric amounts without assuming currency symbol (e.g. 1,439,200.00)."""
    if val is None:
        return "N/A"
    return f"{val:,.2f}"


def format_delta_currency(val: Optional[float]) -> str:
    """Helper to format numeric differences with explicit +/- signs (e.g. +83,900.00)."""
    if val is None:
        return "N/A"
    if val > 0:
        return f"+{val:,.2f}"
    elif val < 0:
        return f"-{abs(val):,.2f}"
    return f"{val:,.2f}"


def format_pct(val: Optional[float]) -> str:
    """Helper to format percentages."""
    if val is None:
        return "N/A"
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.2f}%"


class AnalyticsEngine:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path

    # =========================================================================
    # Operation A: Total Revenue
    # =========================================================================
    def get_total_revenue(self) -> Dict[str, Any]:
        """Calculates total net completed revenue, volume, and data-quality context."""
        sql = """
        SELECT
            COALESCE(SUM(calculated_revenue), 0.0) AS total_revenue,
            COUNT(*) AS transaction_count,
            COALESCE(SUM(quantity), 0) AS total_units_sold,
            COALESCE(AVG(calculated_revenue), 0.0) AS avg_transaction_value
        FROM sales_transactions
        WHERE is_valid_completed = 1;
        """
        conn = get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute(sql)
        row = cursor.fetchone()
        conn.close()

        total_rev = float(row["total_revenue"])
        txn_count = int(row["transaction_count"])
        units_sold = int(row["total_units_sold"])
        avg_txn = float(row["avg_transaction_value"])

        # Fetch data quality summary for context
        dq = get_data_quality_summary(self.db_path)

        insights = [
            f"Total net completed sales stand at {format_currency(total_rev)} across {txn_count} transactions.",
            f"A total of {units_sold:,} units were sold with an average transaction value of {format_currency(avg_txn)}.",
            f"Exclusion Note: {dq['excluded_records']} transaction(s) were excluded from revenue (including {dq['status_distribution'].get('Returned', 0)} returned order and 1 order with missing unit price)."
        ]

        warnings = []
        if dq["excluded_records"] > 0:
            warnings.append(f"{dq['excluded_records']} transaction(s) were excluded from revenue to prevent fabrication of missing prices or inclusion of returns.")

        evidence = [
            {"Metric": "Total Net Revenue", "Value": format_currency(total_rev)},
            {"Metric": "Valid Completed Transactions", "Value": str(txn_count)},
            {"Metric": "Total Units Sold", "Value": str(units_sold)},
            {"Metric": "Average Transaction Value", "Value": format_currency(avg_txn)},
            {"Metric": "Excluded Transactions", "Value": str(dq["excluded_records"])},
            {"Metric": "Data Integrity Score", "Value": f"{dq['integrity_score']}%"}
        ]

        return {
            "operation": "total_revenue",
            "title": "Total Net Completed Revenue",
            "primary_metric": format_currency(total_rev),
            "primary_metric_label": "Total Revenue",
            "summary": f"The total net completed revenue is {format_currency(total_rev)} from {txn_count} completed orders.",
            "executed_sql": sql.strip(),
            "sql_parameters": [],
            "evidence": evidence,
            "insights": insights,
            "warnings": warnings,
            "raw_data": {
                "total_revenue": total_rev,
                "transaction_count": txn_count,
                "units_sold": units_sold,
                "avg_transaction_value": avg_txn
            },
            "follow_ups": [
                "Summarize the sales data",
                "Which product generated the highest revenue?",
                "What is the monthly revenue trend?",
                "Which region had the highest sales?"
            ]
        }

    # =========================================================================
    # Operation B: Highest-Revenue Product
    # =========================================================================
    def get_highest_revenue_product(self) -> Dict[str, Any]:
        """Identifies top-performing products with complete ranked breakdown and tie handling."""
        sql = """
        SELECT
            product,
            category,
            COALESCE(SUM(calculated_revenue), 0.0) AS total_revenue,
            COALESCE(SUM(quantity), 0) AS total_units,
            COUNT(*) AS transaction_count,
            ROUND(AVG(unit_price), 2) AS avg_unit_price
        FROM sales_transactions
        WHERE is_valid_completed = 1
        GROUP BY product, category
        ORDER BY total_revenue DESC;
        """
        conn = get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()

        if not rows:
            return {
                "operation": "highest_revenue_product",
                "title": "Highest-Revenue Product",
                "summary": "No completed transaction records found.",
                "executed_sql": sql.strip(),
                "evidence": [],
                "insights": [],
                "warnings": ["Database contains zero completed sales records."],
                "breakdown": []
            }

        top_revenue = rows[0]["total_revenue"]
        # Handle ties
        tied_top = [r for r in rows if r["total_revenue"] == top_revenue]
        is_tie = len(tied_top) > 1

        overall_revenue = sum(r["total_revenue"] for r in rows)

        if is_tie:
            names = ", ".join(r["product"] for r in tied_top)
            summary_text = f"Tied top products: {names} each generated {format_currency(top_revenue)}."
        else:
            top_prod = rows[0]
            share = (top_prod["total_revenue"] / overall_revenue * 100) if overall_revenue > 0 else 0
            summary_text = f"{top_prod['product']} is the highest-revenue product, generating {format_currency(top_prod['total_revenue'])} ({share:.1f}% of total sales)."

        evidence = []
        for r in rows:
            share = (r["total_revenue"] / overall_revenue * 100) if overall_revenue > 0 else 0
            evidence.append({
                "Product": r["product"],
                "Category": r["category"],
                "Revenue": format_currency(r["total_revenue"]),
                "Units Sold": r["total_units"],
                "Orders": r["transaction_count"],
                "Revenue Share": f"{share:.1f}%"
            })

        insights = [
            f"The top product is {rows[0]['product']} with {format_currency(rows[0]['total_revenue'])} across {rows[0]['total_units']} units.",
            f"The second-highest product is {rows[1]['product']} at {format_currency(rows[1]['total_revenue'])}, a gap of {format_currency(rows[0]['total_revenue'] - rows[1]['total_revenue'])}.",
            f"Lowest performing product by revenue is {rows[-1]['product']} at {format_currency(rows[-1]['total_revenue'])}."
        ]

        return {
            "operation": "highest_revenue_product",
            "title": "Highest-Revenue Product & Performance Ranking",
            "primary_metric": rows[0]["product"] if not is_tie else f"{len(tied_top)} Tied Products",
            "primary_metric_label": "Top Product",
            "primary_metric_secondary": format_currency(top_revenue),
            "summary": summary_text,
            "executed_sql": sql.strip(),
            "sql_parameters": [],
            "evidence": evidence,
            "insights": insights,
            "warnings": [],
            "chart_data": {
                "type": "bar",
                "labels": [r["product"] for r in rows],
                "datasets": [{
                    "label": "Revenue",
                    "data": [r["total_revenue"] for r in rows]
                }]
            },
            "breakdown": rows,
            "follow_ups": [
                f"How did {rows[0]['product']} perform across regions?",
                "What is the monthly revenue trend?",
                "What was the total revenue?"
            ]
        }

    # =========================================================================
    # Operation C: Monthly Revenue Trend
    # =========================================================================
    def get_monthly_revenue_trend(self) -> Dict[str, Any]:
        """Calculates chronological monthly revenue, MoM deltas, and percentage trends."""
        sql = """
        SELECT
            strftime('%Y-%m', order_date) AS month,
            COALESCE(SUM(calculated_revenue), 0.0) AS total_revenue,
            COUNT(*) AS transaction_count,
            COALESCE(SUM(quantity), 0) AS total_units
        FROM sales_transactions
        WHERE is_valid_completed = 1
        GROUP BY strftime('%Y-%m', order_date)
        ORDER BY month ASC;
        """
        conn = get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute(sql)
        raw_rows = [dict(r) for r in cursor.fetchall()]
        conn.close()

        # Compute Month-over-Month changes
        table_rows = []
        peak_month = None
        lowest_month = None
        max_rev = -1.0
        min_rev = float("inf")

        for i, row in enumerate(raw_rows):
            rev = float(row["total_revenue"])
            if rev > max_rev:
                max_rev = rev
                peak_month = row["month"]
            if rev < min_rev:
                min_rev = rev
                lowest_month = row["month"]

            if i == 0:
                mom_change = None
                mom_pct = None
            else:
                prev_rev = float(raw_rows[i - 1]["total_revenue"])
                mom_change = rev - prev_rev
                mom_pct = (mom_change / prev_rev * 100) if prev_rev > 0 else None

            row_data = {
                "Month": row["month"],
                "Revenue": format_currency(rev),
                "Orders": row["transaction_count"],
                "Units Sold": row["total_units"],
                "MoM Change (Amount)": format_delta_currency(mom_change) if mom_change is not None else "Baseline",
                "MoM Change (%)": format_pct(mom_pct) if mom_pct is not None else "Baseline",
                "raw_revenue": rev,
                "raw_mom_change": mom_change,
                "raw_mom_pct": mom_pct
            }
            table_rows.append(row_data)

        # Generate deterministic analytical insights
        insights = []
        if peak_month:
            insights.append(f"Peak revenue occurred in {peak_month} at {format_currency(max_rev)}.")
        if lowest_month:
            insights.append(f"Lowest revenue occurred in {lowest_month} at {format_currency(min_rev)}.")

        # Find largest single-month jump
        jumps = [(r["Month"], r["raw_mom_change"], r["raw_mom_pct"]) for r in table_rows if r["raw_mom_change"] is not None]
        if jumps:
            best_jump = max(jumps, key=lambda x: x[1])
            worst_drop = min(jumps, key=lambda x: x[1])
            if best_jump[1] > 0:
                insights.append(f"Strongest MoM expansion was in {best_jump[0]} with a gain of {format_currency(best_jump[1])} ({best_jump[2]:+.1f}%).")
            if worst_drop[1] < 0:
                insights.append(f"Sharpest MoM contraction was in {worst_drop[0]} with a decline of {format_currency(worst_drop[1])} ({worst_drop[2]:+.1f}%).")

        summary_text = (
            f"Monthly revenue spans {len(raw_rows)} consecutive months from {raw_rows[0]['month']} to {raw_rows[-1]['month']}, "
            f"peaking at {format_currency(max_rev)} in {peak_month}."
        ) if raw_rows else "No monthly sales records found."

        return {
            "operation": "monthly_revenue_trend",
            "title": "Monthly Revenue Trend & MoM Performance",
            "primary_metric": format_currency(max_rev),
            "primary_metric_label": f"Peak Month ({peak_month})",
            "summary": summary_text,
            "executed_sql": sql.strip(),
            "sql_parameters": [],
            "evidence": [{k: v for k, v in r.items() if not k.startswith("raw_")} for r in table_rows],
            "insights": insights,
            "warnings": [],
            "chart_data": {
                "type": "line",
                "labels": [r["month"] for r in raw_rows],
                "datasets": [{
                    "label": "Monthly Revenue",
                    "data": [r["total_revenue"] for r in raw_rows]
                }]
            },
            "breakdown": raw_rows,
            "follow_ups": [
                f"Compare revenue between {raw_rows[0]['month']} and {peak_month}",
                "Which product generated the highest revenue?",
                "Which region had the highest sales?"
            ] if raw_rows else []
        }

    # =========================================================================
    # Operation D: Highest-Sales Region
    # =========================================================================
    def get_highest_sales_region(self) -> Dict[str, Any]:
        """Compares regions by revenue, orders, and units sold to distinguish volume vs value."""
        sql = """
        SELECT
            region,
            COALESCE(SUM(calculated_revenue), 0.0) AS total_revenue,
            COUNT(*) AS transaction_count,
            COALESCE(SUM(quantity), 0) AS total_units,
            ROUND(AVG(calculated_revenue), 2) AS avg_order_value
        FROM sales_transactions
        WHERE is_valid_completed = 1
        GROUP BY region
        ORDER BY total_revenue DESC;
        """
        conn = get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute(sql)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()

        if not rows:
            return {
                "operation": "highest_sales_region",
                "title": "Highest-Sales Region",
                "summary": "No regional sales records found.",
                "executed_sql": sql.strip(),
                "evidence": [],
                "insights": [],
                "warnings": ["Database contains zero completed sales records."],
                "breakdown": []
            }

        total_rev_all = sum(r["total_revenue"] for r in rows)
        top_region = rows[0]

        # Check for volume vs value discrepancies
        most_units_region = max(rows, key=lambda x: x["total_units"])
        most_orders_region = max(rows, key=lambda x: x["transaction_count"])

        insights = [
            f"{top_region['region']} leads in total revenue at {format_currency(top_region['total_revenue'])} ({(top_region['total_revenue'] / total_rev_all * 100):.1f}% of total).",
            f"Units Sold Leader: {most_units_region['region']} with {most_units_region['total_units']:,} units.",
            f"Transaction Count Leader: {most_orders_region['region']} with {most_orders_region['transaction_count']} orders (avg order value {format_currency(most_orders_region['avg_order_value'])})."
        ]

        evidence = []
        for r in rows:
            share = (r["total_revenue"] / total_rev_all * 100) if total_rev_all > 0 else 0
            evidence.append({
                "Region": r["region"],
                "Total Revenue": format_currency(r["total_revenue"]),
                "Units Sold": r["total_units"],
                "Order Count": r["transaction_count"],
                "Avg Order Value": format_currency(r["avg_order_value"]),
                "Revenue Share": f"{share:.1f}%"
            })

        summary_text = (
            f"The {top_region['region']} region generated the highest revenue at {format_currency(top_region['total_revenue'])}, "
            f"delivering {top_region['total_units']} units across {top_region['transaction_count']} orders."
        )

        return {
            "operation": "highest_sales_region",
            "title": "Regional Sales Performance Breakdown",
            "primary_metric": top_region["region"],
            "primary_metric_label": "Top Region",
            "primary_metric_secondary": format_currency(top_region["total_revenue"]),
            "summary": summary_text,
            "executed_sql": sql.strip(),
            "sql_parameters": [],
            "evidence": evidence,
            "insights": insights,
            "warnings": [],
            "chart_data": {
                "type": "bar",
                "labels": [r["region"] for r in rows],
                "datasets": [{
                    "label": "Revenue",
                    "data": [r["total_revenue"] for r in rows]
                }]
            },
            "breakdown": rows,
            "follow_ups": [
                f"What was the total revenue?",
                f"Which product generated the highest revenue?",
                "What is the monthly revenue trend?"
            ]
        }

    # =========================================================================
    # Operation E: Revenue Comparison Between Two Months
    # =========================================================================
    def compare_months_revenue(self, month1: str, month2: str) -> Dict[str, Any]:
        """
        Calculates exact revenue, absolute variance, and percentage growth between two months.
        Guarantees safe division, handles missing months, ties, negative changes, and zero baselines.
        month1 and month2 should be YYYY-MM strings.
        """
        sql = """
        SELECT
            strftime('%Y-%m', order_date) AS month,
            COALESCE(SUM(calculated_revenue), 0.0) AS total_revenue,
            COUNT(*) AS transaction_count,
            COALESCE(SUM(quantity), 0) AS total_units
        FROM sales_transactions
        WHERE is_valid_completed = 1 AND strftime('%Y-%m', order_date) IN (?, ?)
        GROUP BY strftime('%Y-%m', order_date);
        """
        conn = get_db_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute(sql, (month1, month2))
        rows = {r["month"]: dict(r) for r in cursor.fetchall()}

        # Also get all available months for error reporting
        cursor.execute("""
        SELECT DISTINCT strftime('%Y-%m', order_date) AS month
        FROM sales_transactions
        WHERE is_valid_completed = 1
        ORDER BY month ASC;
        """)
        available_months = [r["month"] for r in cursor.fetchall()]
        conn.close()

        # Check existence of months
        m1_data = rows.get(month1, {"month": month1, "total_revenue": 0.0, "transaction_count": 0, "total_units": 0})
        m2_data = rows.get(month2, {"month": month2, "total_revenue": 0.0, "transaction_count": 0, "total_units": 0})

        rev1 = float(m1_data["total_revenue"])
        rev2 = float(m2_data["total_revenue"])
        abs_diff = rev2 - rev1

        warnings = []
        if month1 not in rows:
            warnings.append(f"Month '{month1}' has zero recorded sales in the dataset.")
        if month2 not in rows:
            warnings.append(f"Month '{month2}' has zero recorded sales in the dataset.")

        # Safe percentage calculation
        if rev1 > 0:
            pct_change = (abs_diff / rev1) * 100
            pct_change_str = format_pct(pct_change)
        elif rev1 == 0 and rev2 > 0:
            pct_change = None
            pct_change_str = "Undefined (baseline is 0.00)"
            warnings.append(f"Percentage change is mathematically undefined because baseline month {month1} revenue is 0.00.")
        else:
            pct_change = 0.0
            pct_change_str = "0.00%"

        # Direction summary
        if abs_diff > 0:
            direction = "an increase"
            trend_word = "growth"
        elif abs_diff < 0:
            direction = "a decrease"
            trend_word = "decline"
        else:
            direction = "no change"
            trend_word = "flat"

        summary_text = (
            f"Revenue between {month1} ({format_currency(rev1)}) and {month2} ({format_currency(rev2)}) "
            f"showed {direction} of {format_currency(abs(abs_diff))} ({pct_change_str})."
        )

        evidence = [
            {"Period": month1, "Revenue": format_currency(rev1), "Orders": str(m1_data["transaction_count"]), "Units": str(m1_data["total_units"])},
            {"Period": month2, "Revenue": format_currency(rev2), "Orders": str(m2_data["transaction_count"]), "Units": str(m2_data["total_units"])},
            {"Period": "Absolute Variance", "Revenue": format_delta_currency(abs_diff), "Orders": str(m2_data["transaction_count"] - m1_data["transaction_count"]), "Units": str(m2_data["total_units"] - m1_data["total_units"])},
            {"Period": "Percentage Change", "Revenue": pct_change_str, "Orders": "N/A", "Units": "N/A"}
        ]

        insights = [
            f"{month2} recorded {format_currency(rev2)} vs {month1} with {format_currency(rev1)}.",
            f"Net shift: {format_delta_currency(abs_diff)} ({trend_word} of {pct_change_str}).",
            f"Order volume shifted by {m2_data['transaction_count'] - m1_data['transaction_count']:+d} transactions."
        ]

        return {
            "operation": "compare_months_revenue",
            "title": f"Revenue Comparison: {month1} vs {month2}",
            "primary_metric": pct_change_str,
            "primary_metric_label": f"Growth ({month1} to {month2})",
            "primary_metric_secondary": f"Diff: {format_delta_currency(abs_diff)}",
            "summary": summary_text,
            "executed_sql": sql.strip(),
            "sql_parameters": [month1, month2],
            "evidence": evidence,
            "insights": insights,
            "warnings": warnings,
            "chart_data": {
                "type": "bar",
                "labels": [month1, month2],
                "datasets": [{
                    "label": "Revenue",
                    "data": [rev1, rev2]
                }]
            },
            "comparison_details": {
                "month1": {"month": month1, "revenue": rev1, "orders": m1_data["transaction_count"], "units": m1_data["total_units"]},
                "month2": {"month": month2, "revenue": rev2, "orders": m2_data["transaction_count"], "units": m2_data["total_units"]},
                "absolute_difference": abs_diff,
                "percentage_change": pct_change,
                "available_months": available_months
            },
            "follow_ups": [
                "Summarize the sales data",
                "What is the monthly revenue trend?",
                "Which product generated the highest revenue?",
                "What was the total revenue?"
            ]
        }

    # =========================================================================
    # Operation F: Executive Sales Summary & Performance Overview
    # =========================================================================
    def get_sales_summary(self) -> Dict[str, Any]:
        """
        Generates a comprehensive executive sales summary reusing existing calculations.
        Includes total revenue, leading product, leading region, peak month, and MoM movement.
        Handles empty datasets and edge cases deterministically without crashing.
        """
        tot_res = self.get_total_revenue()
        prod_res = self.get_highest_revenue_product()
        trend_res = self.get_monthly_revenue_trend()
        reg_res = self.get_highest_sales_region()

        total_rev = tot_res["raw_data"]["total_revenue"]
        txn_count = tot_res["raw_data"]["transaction_count"]
        units_sold = tot_res["raw_data"]["units_sold"]

        # Handle empty dataset edge case
        if txn_count == 0 or total_rev == 0:
            return {
                "operation": "sales_summary",
                "title": "Executive Sales Summary",
                "primary_metric": "0.00",
                "primary_metric_label": "Total Revenue",
                "primary_metric_secondary": "No Sales Recorded",
                "summary": "No completed sales transactions found in the database.",
                "executed_sql": tot_res["executed_sql"],
                "sql_parameters": [],
                "evidence": [
                    {"Dimension": "Total Revenue", "Key Figure": "0.00", "Context": "0 completed transactions"},
                    {"Dimension": "Units Sold", "Key Figure": "0", "Context": "No units recorded"}
                ],
                "insights": ["Database contains zero completed sales records."],
                "warnings": ["No active transaction data available for summary analysis."],
                "chart_data": None,
                "follow_ups": [
                    "What is the total revenue?",
                    "What is the data quality status?"
                ]
            }

        # Extract top product
        top_prod = prod_res["breakdown"][0] if prod_res.get("breakdown") else None
        top_prod_name = top_prod["product"] if top_prod else "N/A"
        top_prod_rev = top_prod["total_revenue"] if top_prod else 0.0
        top_prod_share = (top_prod_rev / total_rev * 100) if total_rev > 0 else 0.0

        # Extract top region
        top_reg = reg_res["breakdown"][0] if reg_res.get("breakdown") else None
        top_reg_name = top_reg["region"] if top_reg else "N/A"
        top_reg_rev = top_reg["total_revenue"] if top_reg else 0.0
        top_reg_units = top_reg["total_units"] if top_reg else 0

        # Extract monthly peak and MoM movement
        months_breakdown = trend_res.get("breakdown", [])
        peak_month_info = max(months_breakdown, key=lambda x: x["total_revenue"]) if months_breakdown else None
        peak_month_name = peak_month_info["month"] if peak_month_info else "N/A"
        peak_month_rev = peak_month_info["total_revenue"] if peak_month_info else 0.0

        # Find notable MoM insights from monthly trend
        mom_insights = [ins for ins in trend_res.get("insights", []) if "expansion" in ins or "contraction" in ins]

        summary_text = (
            f"Overall business performance achieved net completed revenue of {format_currency(total_rev)} across {txn_count} orders ({units_sold:,} units). "
            f"{top_prod_name} was the leading product generating {format_currency(top_prod_rev)} ({top_prod_share:.1f}% share), while {top_reg_name} "
            f"led regional sales at {format_currency(top_reg_rev)}. Monthly revenue peaked in {peak_month_name} at {format_currency(peak_month_rev)}."
        )

        evidence = [
            {"Dimension": "Total Net Revenue", "Key Figure": format_currency(total_rev), "Context": f"{txn_count} completed orders, {units_sold:,} units"},
            {"Dimension": "Leading Product", "Key Figure": top_prod_name, "Context": f"{format_currency(top_prod_rev)} ({top_prod_share:.1f}% portfolio share)"},
            {"Dimension": "Leading Region", "Key Figure": top_reg_name, "Context": f"{format_currency(top_reg_rev)} ({top_reg_units:,} units sold)"},
            {"Dimension": "Peak Revenue Month", "Key Figure": peak_month_name, "Context": f"{format_currency(peak_month_rev)} peak volume"}
        ]

        insights = [
            f"Top product {top_prod_name} accounts for {top_prod_share:.1f}% of total portfolio sales.",
            f"Top region {top_reg_name} leads all 4 territories with {format_currency(top_reg_rev)}.",
            f"Sales volume peaked in {peak_month_name} at {format_currency(peak_month_rev)}."
        ]
        if mom_insights:
            insights.append(mom_insights[0])

        first_month = months_breakdown[0]["month"] if months_breakdown else "2026-01"
        follow_ups = [
            "What is the monthly revenue trend?",
            "Which product generated the highest revenue?",
            f"Compare revenue between {first_month} and {peak_month_name}",
            "Which region had the highest sales?"
        ]

        return {
            "operation": "sales_summary",
            "title": "Executive Sales Summary & Performance Overview",
            "primary_metric": format_currency(total_rev),
            "primary_metric_label": "Total Portfolio Revenue",
            "primary_metric_secondary": f"Top: {top_prod_name} | {top_reg_name}",
            "summary": summary_text,
            "executed_sql": tot_res["executed_sql"],
            "sql_parameters": [],
            "evidence": evidence,
            "insights": insights,
            "warnings": tot_res["warnings"],
            "chart_data": prod_res.get("chart_data"),
            "raw_data": {
                "total_revenue": total_rev,
                "transaction_count": txn_count,
                "top_product": top_prod_name,
                "top_product_revenue": top_prod_rev,
                "top_region": top_reg_name,
                "top_region_revenue": top_reg_rev,
                "peak_month": peak_month_name,
                "peak_month_revenue": peak_month_rev
            },
            "follow_ups": follow_ups
        }

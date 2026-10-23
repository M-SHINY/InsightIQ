# Senior Engineering Interview Notes — InsightIQ

**Target Assessment:** RSG Graduate Engineer Trainee Technical Defense
**Topic:** Architectural decisions, system integrity, defensive programming, and code extensibility

---

## 1. Why SQLite Was Chosen

1. **Deterministic, Zero-Latency Embedded Database:** SQLite is an in-process, self-contained, serverless engine. It eliminates network overhead and configuration friction while delivering microsecond-level query response times ($<1.5\text{ ms}$).
2. **ACID Compliance & Standards-Compliant SQL:** SQLite enforces transactional consistency, relational integrity, and standard SQL date-time functions (`strftime`), allowing identical SQL logic to be ported seamlessly to PostgreSQL or Snowflake in production.
3. **Reproducible Local Evaluation:** Eliminates external database server dependencies (e.g. Docker, MySQL, Postgres), ensuring the evaluator can run the application immediately with standard Python standard libraries.

---

## 2. How Data Is Cleaned and Stored

Data integrity is the bedrock of business intelligence:
- **Date Normalization:** CSV dates in `DD-MM-YYYY` format are normalized to ISO-8601 `YYYY-MM-DD` strings during ingestion. This enables lexicographical sorting and native SQLite date aggregation via `strftime('%Y-%m', order_date)`.
- **Handling Missing Values (`TXN0051`):** `Unit_price` is missing in `TXN0051`. Rather than fabricating a fictitious price or making an unverified guess, the record is flagged with `MISSING_UNIT_PRICE` and marked with `is_valid_completed = 0`. It is explicitly excluded from revenue totals and reported in the data quality audit log.
- **Handling Returned Orders (`TXN0033`):** Orders with `status = 'Returned'` represent reversed transactions. To prevent overstating net sales, `TXN0033` is excluded from completed revenue calculations and audited separately.
- **Handling Zero Quantities (`TXN0034`):** Recorded with `Quantity = 0`. Evaluated with \$0.00 revenue and 0 units sold, retaining transactional auditability without distorting volume averages.
- **Lump-Sum Discounts:** Evaluated as transaction-level deductions:
  $$\text{Net Revenue} = (\text{Quantity} \times \text{Unit\_Price}) - \text{Discount\_Amount}$$

---

## 3. How the Five SQL-Backed Analytical Operations Work

All five core challenge questions are executed as parameterized, read-only SQL queries in `analytics.py`:

### A. Total Revenue
```sql
SELECT
    COALESCE(SUM(calculated_revenue), 0.0) AS total_revenue,
    COUNT(*) AS transaction_count,
    COALESCE(SUM(quantity), 0) AS total_units_sold,
    COALESCE(AVG(calculated_revenue), 0.0) AS avg_transaction_value
FROM sales_transactions
WHERE is_valid_completed = 1;
```
*Result:* 1,439,200.00 across 49 valid completed orders.

### B. Highest-Revenue Product
```sql
SELECT
    product, category,
    COALESCE(SUM(calculated_revenue), 0.0) AS total_revenue,
    COALESCE(SUM(quantity), 0) AS total_units,
    COUNT(*) AS transaction_count,
    ROUND(AVG(unit_price), 2) AS avg_unit_price
FROM sales_transactions
WHERE is_valid_completed = 1
GROUP BY product, category
ORDER BY total_revenue DESC;
```
*Result:* Monitor leads at 473,000.00 (32.9% market share). Handles product ties cleanly.

### C. Monthly Revenue Trend
```sql
SELECT
    strftime('%Y-%m', order_date) AS month,
    COALESCE(SUM(calculated_revenue), 0.0) AS total_revenue,
    COUNT(*) AS transaction_count,
    COALESCE(SUM(quantity), 0) AS total_units
FROM sales_transactions
WHERE is_valid_completed = 1
GROUP BY strftime('%Y-%m', order_date)
ORDER BY month ASC;
```
*Result:* 6 consecutive months (2026-01 to 2026-06). Computes Month-over-Month (MoM) absolute and percentage delta for each consecutive month, identifying peak sales in May 2026 (318,500.00).

### D. Highest-Sales Region
```sql
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
```
*Result:* South leads in net revenue (411,200.00, 182 units, 13 orders), while North leads in order volume (14 orders).

### E. Revenue Comparison Between Two Months
```sql
SELECT
    strftime('%Y-%m', order_date) AS month,
    COALESCE(SUM(calculated_revenue), 0.0) AS total_revenue,
    COUNT(*) AS transaction_count,
    COALESCE(SUM(quantity), 0) AS total_units
FROM sales_transactions
WHERE is_valid_completed = 1 AND strftime('%Y-%m', order_date) IN (?, ?)
GROUP BY strftime('%Y-%m', order_date);
```
*Result:* Compares any two requested months (e.g. Feb 2026 at 234,600.00 vs May 2026 at 318,500.00: +83,900.00, +35.76%). Handles zero baseline revenue safely by flagging percentage change as undefined rather than throwing a division by zero error.

### F. Executive Sales Summary & Overview
Deterministically combines key operational dimensions into a cohesive executive briefing:
- Total completed revenue and transaction volume from `get_total_revenue()`
- Leading product and share from `get_highest_revenue_product()`
- Leading territory from `get_highest_sales_region()`
- Peak revenue month and MoM movement from `get_monthly_revenue_trend()`
- Zero baseline and empty database edge cases handled safely without division by zero.

---

## 4. How Natural-Language Interpretation Differs From Calculation

- **Separation of Concerns:** In production systems, natural language processing (NLP) is inherently probabilistic, while financial calculations must be deterministic.
- **Risk Mitigation:** If an LLM is asked to compute "the sum of monitor sales minus discounts", it will approximate or hallucinate tokens, fail on large record counts, and produce inconsistent outputs between calls.
- **The InsightIQ Solution:** The AI system acts exclusively as an **intent router** (classifying user intent into an allowlisted enum: `TOTAL_REVENUE`, `SALES_SUMMARY`, `COMPARE_MONTHS`, etc., and extracting parameters like `"2026-02"` and `"2026-05"`). The numbers are calculated strictly by the SQL engine.

---

## 5. How LLM Output Is Validated & How SQL Injection Is Prevented

1. **Pydantic Intent Validation:** All model outputs are validated against the `QueryIntent` Pydantic model. If a model generates unknown intents or malformed parameters, Pydantic raises a validation error, triggering the fallback interpreter.
2. **Zero Dynamic SQL Generation:** The LLM is never permitted to write SQL syntax.
3. **Malicious Input Detector:** Before questions reach the interpreter, a regex sanitizer screens for destructive patterns (`DROP`, `DELETE`, `UNION`, `--`, `;`).
4. **Parameterized SQL:** All SQL queries use SQLite `?` bind parameters, completely preventing SQL injection.

---

## 6. Why a Fallback Interpreter Exists

1. **Guaranteed High Availability:** External LLM APIs can suffer outages, latency spikes, rate limits, or require subscription keys.
2. **Offline Resilience:** For candidate evaluation or on-premise air-gapped environments, InsightIQ runs 100% locally with zero cloud dependencies.
3. **Equivalence of Contract:** The fallback parser emits the exact same Pydantic `QueryIntent` schema as the LLM adapter, making the downstream analytics pipeline completely agnostic to the interpreter mode.

---

## 7. How the REST API Works

- **`POST /api/query`:** Accepts `{"question": "..."}`. Returns structured JSON containing primary metric, title, summary, executed SQL, evidence table, insights list, follow-ups, and latency.
- **`GET /api/data-quality`:** Exposes full audit metrics, record status distributions, exclusion details, and the official revenue policy.
- **`GET /api/history`:** Provides session-level history of recent user queries and results for reproducibility.
- **`GET /api/health`:** Diagnostic endpoint reporting database status and active interpreter mode.

---

## 8. What the Test Suite Establishes

InsightIQ features 38 automated tests in `tests/` covering:
- Mathematical correctness of all analytical operations (Total Revenue, Top Product, Monthly Trend, Top Region, Month Comparison, Sales Summary).
- Edge cases: product ties, zero baselines, identical month comparisons, empty databases, missing months.
- Data quality: exclusion of missing unit price rows, exclusion of returned orders, warning on zero quantity rows.
- NLP parser: flexible date formats (e.g., "February 2026", "Feb vs May", "2026-01"), executive summary queries, and polite rejection of out-of-scope non-sales inquiries.
- Security: SQL injection defenses, out-of-scope question rejection, empty query rejection.
- REST API contracts: valid schemas, HTTP status codes, error handling, session history.

---

## 9. Walkthrough: How to Add a 6th Analytical Question

To demonstrate the clean modular architecture, here is the exact 3-step procedure to add a new question (e.g., *"Sales performance by channel"*):

### Step 1: Add Analytics Method in `analytics.py`
```python
def get_channel_performance(self) -> Dict[str, Any]:
    sql = """
    SELECT
        sales_channel,
        COALESCE(SUM(calculated_revenue), 0.0) AS total_revenue,
        COUNT(*) AS transaction_count,
        COALESCE(SUM(quantity), 0) AS total_units
    FROM sales_transactions
    WHERE is_valid_completed = 1
    GROUP BY sales_channel
    ORDER BY total_revenue DESC;
    """
    # Execute query, bundle evidence, generate insights, and return structured dict
```

### Step 2: Register Intent in `interpreter.py`
1. Add `CHANNEL_PERFORMANCE = "channel_performance"` to `IntentType(str, Enum)`.
2. Add keyword match rule in `FallbackRuleInterpreter.interpret()`:
   ```python
   if any(k in q for k in ["channel", "sales channel", "online vs retail"]):
       return QueryIntent(intent=IntentType.CHANNEL_PERFORMANCE, ...)
   ```
3. Update `QueryDispatcher.process_query()` to route `CHANNEL_PERFORMANCE` to `self.engine.get_channel_performance()`.

### Step 3: Add Automated Test in `tests/test_analytics.py`
```python
def test_channel_performance(engine):
    res = engine.get_channel_performance()
    assert res["operation"] == "channel_performance"
    assert len(res["evidence"]) == 2  # Online and Retail
```
Because of the decoupled architecture, no frontend rewrites or database migrations are required! The UI will render the KPI card, evidence table, insights, and executed SQL automatically.

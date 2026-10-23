# AI Development Report — InsightIQ

**Project:** InsightIQ — Trustworthy AI Sales Intelligence
**Engineer / Author:** Graduate Engineer Trainee Candidate
**Date:** 2026-10-23
**Review Target:** Senior Software Engineering Assessment

---

## 1. Executive Summary & Mission

The objective was to engineer a robust, production-minded Mini AI Business Intelligence Assistant capable of answering five core analytical questions on a real-world enterprise sales dataset.

The central engineering challenge in enterprise AI analytics is **preventing hallucinations and destructive operations**. Generative LLMs frequently make subtle calculation errors (such as sum errors, improper date groupings, or hallucinations) when calculating metrics directly over unstructured data. Furthermore, allowing an LLM to generate unrestricted SQL strings creates severe SQL injection and data-corruption vulnerabilities.

InsightIQ solves this through a **strict decoupled hybrid architecture**:
- **Natural Language Intent Recognition:** Translates natural language inquiries into a strongly typed, allowlisted Pydantic intent schema.
- **Deterministic Analytics Execution:** Maps validated intents to parameterized, read-only SQL queries executed directly in SQLite.
- **Fail-Safe Fallbacks:** Provides a 100% deterministic, rule-based semantic parser so that the application functions seamlessly offline without requiring third-party API keys.

---

## 2. Actual AI Usage & Architecture Decisions

### A. Intent Interpretation vs. Calculation
We made a conscious architectural decision: **LLMs must never perform business calculations directly.**
- In InsightIQ, the LLM adapter (using Google Gemini or OpenAI) acts strictly as a semantic classifier: it parses query parameters (such as `month1` and `month2`) and maps the question to one of the 5 approved analytical operations.
- Calculations are performed deterministically in SQLite using native aggregation functions (`SUM`, `COUNT`, `AVG`, `strftime`).

### B. Dual-Mode Interpretation & Resilience
To ensure zero failure states during evaluation or offline execution:
1. **Configurable LLM Adapter:** If `GEMINI_API_KEY` or `OPENAI_API_KEY` is present in the environment, the application uses the LLM to classify questions.
2. **Deterministic Fallback Parser:** If no API key is present or if the network request fails, the application automatically switches to `fallback_rules`.
3. **Response Transparency:** Every API response explicitly flags the mode used (`"llm_gemini"` or `"fallback_rules"`), latency in milliseconds, and interpretation explanation.

---

## 3. Real Debugging Experiences & Issues Resolved

During development, several concrete technical challenges were encountered and resolved:

### Issue 1: Regex Month Token Parsing at String Boundaries
- **Symptom:** In `test_month_token_parsing`, the question `"March vs April"` correctly extracted `"2026-03"`, but missed `"April"`.
- **Root Cause Analysis:** The initial regex pattern was `r"\b(january|...)\b[\s,]+(202\d|\d{2})?"`. Because of the mandatory `[\s,]+` following the month name, a month located at the end of the query string with no trailing whitespace failed to match.
- **Resolution:** Replaced the greedy whitespace requirement with a non-capturing optional group: `r"\b(january|...)\b(?:[\s,]+(202\d|\d{2}))?"`. All month variations (with or without explicit years, at any position in the sentence) now parse cleanly.

### Issue 2: Explicit Sign Representation and Currency Neutrality
- **Symptom:** Month-over-month deltas and comparative differences initially formatted without explicit positive signs (`24,350.00` rather than `+24,350.00`), and assumed a USD currency symbol `$`.
- **Root Cause Analysis:** The sales dataset does not specify a currency (e.g. USD, INR). Labeling amounts as USD without evidence violated data fidelity. Furthermore, in business analytics, distinguishing positive expansion (`+24,350.00`) from contraction (`-10,700.00`) is critical.
- **Resolution:** Implemented `format_delta_currency(val)` which explicitly prepends `+` for positive variances, `-` for negative variances, and outputs clean localized decimal numbers without assumed currency symbols.

### Issue 3: Sandboxed Loopback Socket Execution vs. WSGI Client
- **Symptom:** Attempting to run a live HTTP socket test using `urllib.request.urlopen("http://127.0.0.1:5055")` inside standard sandbox mode triggered `PermissionError: [Errno 1] Operation not permitted`.
- **Root Cause Analysis:** The secure sandbox blocks opening raw OS TCP sockets by default.
- **Resolution:** Verified that Flask's in-process test client (`app.test_client()`) operates natively via the WSGI specification without opening network sockets. We constructed end-to-end integration tests using the WSGI client, validating all endpoints, status codes, latency measurements, and session history cleanly.

### Issue 4: Deterministic Executive Sales Summary & Context-Aware Follow-ups
- **Symptom:** Users asking broad questions like "Summarize the sales data" or "Give me an overview of sales performance" needed an executive briefing combining total revenue, leading product, leading region, and peak month without allowing an LLM to hallucinate values or run unconstrained SQL. Furthermore, out-of-scope questions risked either failing silently or being misclassified.
- **Root Cause Analysis:** General overview questions require synthesizing multiple analytical dimensions. If sent to an LLM, figures could easily be invented. If handled by a brittle regex, unrelated queries like "Summarize the history of Rome" could accidentally trigger the sales summary.
- **Resolution:** Implemented `get_sales_summary()` in `AnalyticsEngine`, reusing existing deterministic calculations (`get_total_revenue()`, `get_highest_revenue_product()`, etc.) and handling edge cases like empty datasets (`0.00` revenue). In `FallbackRuleInterpreter`, required that summary keywords co-occur with sales/business domain tokens, ensuring non-sales questions map strictly to `UNSUPPORTED_QUESTION` with polite guidance and example prompts. Context-aware follow-ups (`follow_ups`) were added to every response, enabling one-click query exploration.

---

## 4. Status Table & Implementation Checklist

In accordance with Section 12 of the requirements, here is the honest four-state status table:

| Capability / Component | State | Verification Evidence |
| :--- | :---: | :--- |
| **CSV Ingestion & SQLite Database** | Implemented and tested | 51 records loaded, schema indexed, audit log populated |
| **Data Cleaning & Exclusion Logic** | Implemented and tested | `TXN0051` (missing price) & `TXN0033` (returned) excluded; `TXN0034` zero qty flagged; duplicates rejected |
| **Total Revenue Operation** | Implemented and tested | Deterministic calculation: 1,439,200.00; verified in pytest & API |
| **Highest-Revenue Product Operation** | Implemented and tested | Monitor (473,000.00); tie-breaking logic verified in test |
| **Monthly Revenue Trend Operation** | Implemented and tested | Chronological 6 months, peak May (318,500.00), MoM deltas verified |
| **Highest-Sales Region Operation** | Implemented and tested | South (411,200.00, 182 units); 4-region breakdown verified |
| **Two-Month Comparison Operation** | Implemented and tested | Feb vs May (+83,900.00, +35.76%); zero baseline and missing months verified |
| **Executive Sales Summary** | Implemented and tested | Deterministic multi-dimensional synthesis (1,439,200.00 total, Monitor, South, May peak) |
| **Context-Aware Follow-up Chips** | Implemented and tested | Dynamic, clickable follow-up suggestions in all responses |
| **Polite Rejection of Out-of-Scope Inquiries** | Implemented and tested | Explains sales focus and presents supported examples without false classification |
| **SQL Safety & Injection Prevention** | Implemented and tested | Multi-layer defense: allowlist dispatch + regex malicious detector |
| **Fallback NLP Interpreter** | Implemented and tested | 100% test pass rate for all challenge questions, summaries & date formats |
| **LLM Adapter (Gemini / OpenAI)** | Implemented and tested | Dual-mode adapter with Pydantic validation; mock & fallback tests verified |
| **Web Dashboard User Interface** | Implemented and tested | HTML5, CSS3, Chart.js, responsive layouts, data modal, follow-ups verified |
| **Automated Testing Suite (38 Tests)**| Implemented and tested | `./test.sh` executes 38/38 passing in 0.51s |
| **SQL & Decision Transparency Drawer**| Implemented and tested | Displays exact executed SQL, bind parameters, and intent mapping |
| **Query History Bar** | Implemented and tested | Session-level history tracking and one-click query replay verified |
| **Data Quality & Revenue Policy Modal**| Implemented and tested | Interactive modal surfacing data health, issue table, policy formula |

---

## 5. Automated Verification Summary

All 38 tests in `tests/` pass with zero warnings or regressions:

```
============================== test session starts ==============================
platform darwin -- Python 3.12.4, pytest-9.0.2, pluggy-1.6.0
rootdir: /Users/shinymotana/Desktop/InsightIQ

tests/test_analytics.py::test_total_revenue_calculation PASSED           [  2%]
tests/test_analytics.py::test_highest_revenue_product PASSED             [  5%]
tests/test_analytics.py::test_monthly_revenue_trend PASSED               [  7%]
tests/test_analytics.py::test_highest_sales_region PASSED                [ 10%]
tests/test_analytics.py::test_compare_months_revenue_valid PASSED        [ 13%]
tests/test_analytics.py::test_compare_months_revenue_zero_baseline PASSED [ 15%]
tests/test_analytics.py::test_compare_months_revenue_identical_months PASSED [ 18%]
tests/test_analytics.py::test_sales_summary PASSED                       [ 21%]
tests/test_analytics.py::test_sales_summary_empty_database PASSED        [ 23%]
tests/test_analytics.py::test_product_tie_handling PASSED                [ 26%]
tests/test_api.py::test_api_health PASSED                                [ 28%]
tests/test_api.py::test_api_data_quality PASSED                          [ 31%]
tests/test_api.py::test_api_query_success PASSED                         [ 34%]
tests/test_api.py::test_api_query_missing_json PASSED                    [ 36%]
tests/test_api.py::test_api_query_empty_question PASSED                  [ 39%]
tests/test_api.py::test_api_history_tracking PASSED                      [ 42%]
tests/test_api.py::test_api_sales_summary PASSED                         [ 44%]
tests/test_api.py::test_api_unsupported_question PASSED                  [ 47%]
tests/test_data_quality.py::test_missing_unit_price_exclusion PASSED     [ 50%]
tests/test_data_quality.py::test_returned_transaction_exclusion PASSED   [ 52%]
tests/test_data_quality.py::test_zero_quantity_handling PASSED           [ 55%]
tests/test_data_quality.py::test_discount_subtraction PASSED             [ 57%]
tests/test_data_quality.py::test_data_quality_summary_metrics PASSED     [ 60%]
tests/test_data_quality.py::test_duplicate_and_invalid_date_rejection PASSED [ 63%]
tests/test_interpreter.py::test_intent_mapping_total_revenue PASSED      [ 65%]
tests/test_interpreter.py::test_intent_mapping_highest_revenue_product PASSED [ 68%]
tests/test_interpreter.py::test_intent_mapping_monthly_trend PASSED      [ 71%]
tests/test_interpreter.py::test_intent_mapping_highest_sales_region PASSED [ 73%]
tests/test_interpreter.py::test_intent_mapping_compare_months PASSED     [ 76%]
tests/test_interpreter.py::test_month_token_parsing PASSED               [ 78%]
tests/test_interpreter.py::test_sql_injection_defense PASSED             [ 81%]
tests/test_interpreter.py::test_unsupported_out_of_scope_question PASSED [ 84%]
tests/test_interpreter.py::test_empty_query_validation PASSED            [ 86%]
tests/test_interpreter.py::test_llm_adapter_active_path PASSED           [ 89%]
tests/test_interpreter.py::test_llm_adapter_failure_fallback PASSED      [ 92%]
tests/test_interpreter.py::test_intent_mapping_sales_summary PASSED      [ 94%]
tests/test_interpreter.py::test_unrelated_questions_rejected_not_summarized PASSED [ 97%]
tests/test_interpreter.py::test_follow_up_suggestions_in_all_operations PASSED [100%]

============================== 38 passed in 0.51s ==============================
```

---

## 6. Limitations & Roadmap for Future Iterations

If granted an additional development sprint, the following architectural enhancements would be prioritized:
1. **Multi-Table Normalization:** Break `sales_transactions` into third normal form (`dim_products`, `dim_regions`, `dim_customers`, `fact_sales`) to support complex enterprise data pipelines.
2. **Persistent Query History:** Migrate the current in-memory session history to an SQLite audit log or Redis cache for persistent user auditing.
3. **Automated Data Quality Remediation:** Allow data stewards to review flagged records (e.g., `TXN0051`) and approve imputation or catalog price lookup through a secure review workflow.
4. **Vector / Semantic Embeddings for Ad-Hoc Analytics:** Integrate local embeddings (e.g., ChromaDB with sentence-transformers) to support similarity matching over extended product catalogs.

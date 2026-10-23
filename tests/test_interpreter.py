"""
Tests for InsightIQ Interpreter and Security Controls.
Verifies natural language intent mapping, SQL injection defense, and parameter extraction.
"""

import pytest
from interpreter import QueryDispatcher, check_for_malicious_input, parse_month_tokens, IntentType


@pytest.fixture
def dispatcher():
    return QueryDispatcher()


def test_intent_mapping_total_revenue(dispatcher):
    res = dispatcher.process_query("What is our total revenue for the year?")
    assert res["success"] is True
    assert res["interpretation"]["intent"] == IntentType.TOTAL_REVENUE.value
    assert res["operation"] == "total_revenue"


def test_intent_mapping_highest_revenue_product(dispatcher):
    res = dispatcher.process_query("Which product generated the highest revenue?")
    assert res["success"] is True
    assert res["interpretation"]["intent"] == IntentType.HIGHEST_REVENUE_PRODUCT.value
    assert res["operation"] == "highest_revenue_product"


def test_intent_mapping_monthly_trend(dispatcher):
    res = dispatcher.process_query("Show me the monthly revenue trend and breakdown")
    assert res["success"] is True
    assert res["interpretation"]["intent"] == IntentType.MONTHLY_REVENUE_TREND.value
    assert res["operation"] == "monthly_revenue_trend"


def test_intent_mapping_highest_sales_region(dispatcher):
    res = dispatcher.process_query("Which region had the highest sales?")
    assert res["success"] is True
    assert res["interpretation"]["intent"] == IntentType.HIGHEST_SALES_REGION.value
    assert res["operation"] == "highest_sales_region"


def test_intent_mapping_compare_months(dispatcher):
    res = dispatcher.process_query("Compare revenue between February 2026 and May 2026")
    assert res["success"] is True
    assert res["interpretation"]["intent"] == IntentType.COMPARE_MONTHS.value
    assert res["operation"] == "compare_months_revenue"
    assert res["comparison_details"]["month1"]["month"] == "2026-02"
    assert res["comparison_details"]["month2"]["month"] == "2026-05"


def test_month_token_parsing():
    assert parse_month_tokens("Compare Feb 2026 with May 2026") == ["2026-02", "2026-05"]
    assert parse_month_tokens("Compare 2026-01 and 2026-06") == ["2026-01", "2026-06"]
    assert parse_month_tokens("March vs April") == ["2026-03", "2026-04"]


def test_sql_injection_defense(dispatcher):
    """Verify malicious SQL commands are intercepted before execution."""
    queries = [
        "DROP TABLE sales_transactions;",
        "SELECT * FROM sales_transactions WHERE 1=1; DROP TABLE data_quality_log; --",
        "UNION SELECT password, email FROM users",
        "DELETE FROM sales_transactions WHERE id > 0"
    ]
    for q in queries:
        res = dispatcher.process_query(q)
        assert res["success"] is False
        assert res["error"] == "SECURITY_REJECTION"


def test_unsupported_out_of_scope_question(dispatcher):
    """Verify out-of-scope non-sales questions return clean unsupported error."""
    res = dispatcher.process_query("What is the current stock price of Apple?")
    assert res["success"] is False
    assert res["error"] == "UNSUPPORTED_QUESTION"
    assert len(res["supported_questions"]) > 0


def test_empty_query_validation(dispatcher):
    """Verify empty or whitespace-only queries are rejected with error."""
    res = dispatcher.process_query("   ")
    assert res["success"] is False
    assert res["error"] == "EMPTY_QUERY"


def test_llm_adapter_active_path(monkeypatch, dispatcher):
    """Verify that when an LLM adapter is available, its intent is validated and used."""
    from interpreter import QueryIntent

    def mock_interpret(self, question):
        return QueryIntent(
            intent=IntentType.TOTAL_REVENUE,
            confidence=0.99,
            parameters={},
            interpretation_mode="llm_gemini",
            explanation="Classified via mock Gemini LLM."
        )

    monkeypatch.setattr("interpreter.LLMInterpreter.is_available", lambda self: True)
    monkeypatch.setattr("interpreter.LLMInterpreter.interpret", mock_interpret)

    res = dispatcher.process_query("What is our overall sales amount?")
    assert res["success"] is True
    assert res["interpretation"]["mode"] == "llm_gemini"
    assert res["operation"] == "total_revenue"
    assert res["primary_metric"] == "1,439,200.00"


def test_llm_adapter_failure_fallback(monkeypatch, dispatcher):
    """Verify that if LLM raises an error or fails, system transparently falls back to rules."""
    def mock_failing_interpret(self, question):
        return None  # Represents failed network call / timeout

    monkeypatch.setattr("interpreter.LLMInterpreter.is_available", lambda self: True)
    monkeypatch.setattr("interpreter.LLMInterpreter.interpret", mock_failing_interpret)

    res = dispatcher.process_query("What is the total revenue?")
    assert res["success"] is True
    assert res["interpretation"]["mode"] == "fallback_rules"
    assert res["operation"] == "total_revenue"


def test_intent_mapping_sales_summary(dispatcher):
    """Verify sales summary intent mapping for primary and variation phrasing."""
    queries = [
        "Summarize the sales data",
        "Give me an overview of sales performance",
        "Can you provide a sales summary?",
        "Executive summary of sales"
    ]
    for q in queries:
        res = dispatcher.process_query(q)
        assert res["success"] is True, f"Failed for query: {q}"
        assert res["interpretation"]["intent"] == IntentType.SALES_SUMMARY.value
        assert res["operation"] == "sales_summary"
        assert res["primary_metric"] == "1,439,200.00"
        assert len(res["follow_ups"]) >= 3


def test_unrelated_questions_rejected_not_summarized(dispatcher):
    """Verify unrelated questions return polite UNSUPPORTED_QUESTION without misclassifying as summary."""
    unrelated_queries = [
        "Summarize the history of Rome",
        "What is the weather in London?",
        "Write a python script for sorting",
        "Who is the CEO of Google?",
        "Can you help me bake a cake?"
    ]
    for q in unrelated_queries:
        res = dispatcher.process_query(q)
        assert res["success"] is False, f"Should have rejected: {q}"
        assert res["error"] == "UNSUPPORTED_QUESTION"
        assert "specialized business intelligence assistant" in res["message"]
        assert "Summarize the sales data" in res["supported_questions"]


def test_follow_up_suggestions_in_all_operations(dispatcher):
    """Verify every analytical operation returns context-aware follow-up suggestions."""
    test_queries = [
        "What is the total revenue?",
        "What is the highest-revenue product?",
        "What is the monthly revenue trend?",
        "What is the highest-sales region?",
        "Compare revenue between February 2026 and May 2026",
        "Summarize the sales data"
    ]
    for q in test_queries:
        res = dispatcher.process_query(q)
        assert res["success"] is True
        assert "follow_ups" in res
        assert len(res["follow_ups"]) > 0
        for follow_up in res["follow_ups"]:
            assert isinstance(follow_up, str) and len(follow_up) > 5

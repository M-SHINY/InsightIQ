"""
Tests for InsightIQ Flask REST API Endpoints.
Verifies response schemas, status codes, error handling, and history.
"""

import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_api_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] == "healthy"
    assert "database" in data
    assert "interpreter" in data


def test_api_data_quality(client):
    res = client.get("/api/data-quality")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total_records"] == 51
    assert data["valid_completed_records"] == 49
    assert "revenue_policy" in data


def test_api_query_success(client):
    res = client.post("/api/query", json={"question": "What is the total revenue?"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["operation"] == "total_revenue"
    assert data["primary_metric"] == "1,439,200.00"
    assert "executed_sql" in data
    assert "evidence" in data
    assert "insights" in data
    assert "latency_ms" in data


def test_api_query_missing_json(client):
    res = client.post("/api/query", data="plain text", content_type="text/plain")
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert data["error"] == "INVALID_CONTENT_TYPE"


def test_api_query_empty_question(client):
    res = client.post("/api/query", json={"question": ""})
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert data["error"] == "EMPTY_QUERY"


def test_api_history_tracking(client):
    # Execute query
    client.post("/api/query", json={"question": "Which region had the highest sales?"})
    res = client.get("/api/history")
    assert res.status_code == 200
    data = res.get_json()
    assert data["total_queries"] > 0
    assert len(data["history"]) > 0
    latest = data["history"][0]
    assert latest["question"] == "Which region had the highest sales?"
    assert latest["success"] is True


def test_api_sales_summary(client):
    """Verify sales summary end-to-end through the Flask REST API."""
    res = client.post("/api/query", json={"question": "Summarize the sales data"})
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["operation"] == "sales_summary"
    assert data["primary_metric"] == "1,439,200.00"
    assert "Monitor" in data["summary"]
    assert "South" in data["summary"]
    assert "2026-05" in data["summary"]
    assert len(data["follow_ups"]) >= 3


def test_api_unsupported_question(client):
    """Verify polite error message and 400 status for unsupported questions."""
    res = client.post("/api/query", json={"question": "What is the stock price of Apple?"})
    assert res.status_code == 400
    data = res.get_json()
    assert data["success"] is False
    assert data["error"] == "UNSUPPORTED_QUESTION"
    assert "specialized business intelligence assistant" in data["message"]
    assert len(data["supported_questions"]) >= 5

"""
InsightIQ Flask Web Application & REST API
Exposes endpoints for natural language business intelligence queries,
data quality transparency, query history, and health checks.
"""

import os
import time
from typing import Dict, Any, List
from flask import Flask, request, jsonify, render_template
from database import init_db, get_data_quality_summary, DEFAULT_DB_PATH
from interpreter import QueryDispatcher

app = Flask(__name__)

# Initialize database on startup
DB_PATH = os.environ.get("INSIGHTIQ_DB_PATH", DEFAULT_DB_PATH)
init_db(db_path=DB_PATH)

dispatcher = QueryDispatcher(db_path=DB_PATH)

# In-memory session query history (retaining recent queries safely)
QUERY_HISTORY: List[Dict[str, Any]] = []
MAX_HISTORY = 15


@app.route("/")
def index():
    """Serves the main InsightIQ dashboard."""
    return render_template("index.html")


@app.route("/api/query", methods=["POST"])
def handle_query():
    """
    Executes a natural language analytics query.
    Request body: {"question": "..."}
    """
    if not request.is_json:
        return jsonify({
            "success": False,
            "error": "INVALID_CONTENT_TYPE",
            "message": "Request must have Content-Type: application/json."
        }), 400

    payload = request.get_json()
    if not payload or "question" not in payload:
        return jsonify({
            "success": False,
            "error": "MISSING_QUESTION",
            "message": "Field 'question' is required."
        }), 400

    question = str(payload.get("question", "")).strip()
    start_time = time.time()

    # Process query through interpreter and analytics engine
    response = dispatcher.process_query(question)
    latency_ms = round((time.time() - start_time) * 1000, 2)
    response["latency_ms"] = latency_ms

    # Record in session history
    history_entry = {
        "id": len(QUERY_HISTORY) + 1,
        "question": question,
        "timestamp": time.strftime("%H:%M:%S"),
        "success": response.get("success", False),
        "primary_metric": response.get("primary_metric", "Error"),
        "intent": response.get("interpretation", {}).get("intent", "unknown") if response.get("success") else "error",
        "mode": response.get("interpretation", {}).get("mode", "N/A") if response.get("success") else "N/A",
        "latency_ms": latency_ms
    }
    QUERY_HISTORY.insert(0, history_entry)
    if len(QUERY_HISTORY) > MAX_HISTORY:
        QUERY_HISTORY.pop()

    status_code = 200 if response.get("success") else 400
    return jsonify(response), status_code


@app.route("/api/data-quality", methods=["GET"])
def get_data_quality():
    """Returns comprehensive data quality metrics and revenue policy."""
    summary = get_data_quality_summary(DB_PATH)
    return jsonify(summary)


@app.route("/api/history", methods=["GET"])
def get_history():
    """Returns the recent query history for this session."""
    return jsonify({
        "total_queries": len(QUERY_HISTORY),
        "history": QUERY_HISTORY
    })


@app.route("/api/health", methods=["GET"])
def health_check():
    """API health check returning database status and interpreter mode."""
    dq = get_data_quality_summary(DB_PATH)
    llm_available = dispatcher.llm.is_available()
    return jsonify({
        "status": "healthy",
        "database": {
            "path": DB_PATH,
            "total_records": dq["total_records"],
            "valid_completed_records": dq["valid_completed_records"]
        },
        "interpreter": {
            "llm_configured": llm_available,
            "default_mode": "llm" if llm_available else "fallback_rules"
        }
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(host="127.0.0.1", port=port, debug=True)

#!/bin/bash
# InsightIQ Launcher Script
# Automatically uses the virtual environment or Python 3.12 where Flask & Pandas are installed

cd "$(dirname "$0")"

if [ -f "./venv/bin/python" ]; then
    echo "Starting InsightIQ using local virtual environment (Python 3.12)..."
    ./venv/bin/python app.py "$@"
elif command -v python3.12 >/dev/null 2>&1; then
    echo "Starting InsightIQ using Python 3.12..."
    python3.12 app.py "$@"
else
    echo "Starting InsightIQ using system python3..."
    python3 app.py "$@"
fi

#!/bin/bash
# InsightIQ Test Suite Launcher
# Automatically uses the virtual environment or Python 3.12 where pytest is installed

cd "$(dirname "$0")"

if [ -f "./venv/bin/pytest" ]; then
    ./venv/bin/pytest -v tests/ "$@"
elif command -v python3.12 >/dev/null 2>&1; then
    python3.12 -m pytest -v tests/ "$@"
else
    python3 -m pytest -v tests/ "$@"
fi

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Use venv python if it exists, otherwise fall back to system python3
if [[ -f ".venv/bin/python" ]]; then
    PYTHON=".venv/bin/python"
else
    PYTHON="$(command -v python3 || command -v python)"
fi

exec "$PYTHON" "$SCRIPT_DIR/setup.py" "$@"

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

source .venv/bin/activate

CUBLAS_LIB=$(find .venv -name "libcublas.so.12" -exec dirname {} \; 2>/dev/null | head -1)
if [[ -n "$CUBLAS_LIB" ]]; then
    export LD_LIBRARY_PATH="$CUBLAS_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

export YTQUEUE_LLM_PROVIDER=ollama
export YTQUEUE_LLM_MODEL=gemma3:27b
export YTQUEUE_LLM_BASE_URL=http://llm-server:11434

uvicorn app.main:app --host 0.0.0.0 --port 9000

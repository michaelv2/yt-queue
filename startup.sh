#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

CUBLAS_LIB=$(find .venv -name "libcublas.so.12" -exec dirname {} \; 2>/dev/null | head -1)
if [[ -n "$CUBLAS_LIB" ]]; then
    export LD_LIBRARY_PATH="$CUBLAS_LIB${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

export YTQUEUE_BASE_URL=http://localhost:9000
# export YTQUEUE_WHISPER_DEVICES=cuda:0,cuda:1  # uncomment for multi-GPU parallelism
export YTQUEUE_LLM_PROVIDER=ollama
export YTQUEUE_LLM_MODEL=gemma3:27b
export YTQUEUE_LLM_BASE_URL=http://llm-server:11434
export YTQUEUE_MAX_DURATION_SECONDS=26000

exec "$VENV_PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port 9000

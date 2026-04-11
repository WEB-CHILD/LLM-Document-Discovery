#!/usr/bin/env bash
# On-node pipeline orchestration
# No set -euo pipefail — EXIT trap MUST always fire for server cleanup
#
# Required env vars: VLLM_MODEL, VLLM_TP, VLLM_GPU_MEM, VLLM_MAX_SEQS
# Optional: VLLM_PORT, DB_PATH, INPUT_DIR, OUTPUT_DIR

# 1. Install GPU dependencies
uv sync --extra gpu

# 2. Read config from environment (set by HPC job script)
VLLM_PORT="${VLLM_PORT:-8000}"
DB_PATH="${DB_PATH:-corpus.db}"
INPUT_DIR="${INPUT_DIR:-input/demo_corpus}"
OUTPUT_DIR="${OUTPUT_DIR:-out}"

# 3. Start vLLM server in tmux session
tmux new-session -d -s llm-server "bash scripts/start_server.sh"

# 4. EXIT trap — cleanup server regardless of exit reason
trap 'tmux kill-session -t llm-server 2>/dev/null' EXIT

# 5. Wait for server health
echo "Waiting for vLLM server on port ${VLLM_PORT}..."
MAX_WAIT=3600
WAITED=0
while ! curl -sf "http://localhost:${VLLM_PORT}/health" > /dev/null 2>&1; do
    sleep 5
    WAITED=$((WAITED + 5))
    if [ "$WAITED" -ge "$MAX_WAIT" ]; then
        echo "ERROR: vLLM server did not start within ${MAX_WAIT}s"
        exit 1
    fi
done
echo "vLLM server is healthy"

# 6. Run pipeline sequentially via Typer CLI
uv run llm-discovery prep-db \
    --db "$DB_PATH" \
    --input-dir "$INPUT_DIR" || exit 1

uv run llm-discovery preflight \
    --db "$DB_PATH" || exit 1

uv run llm-discovery process \
    --db "$DB_PATH" \
    --output-dir "$OUTPUT_DIR" \
    --server-url "http://localhost:${VLLM_PORT}" || exit 1

uv run llm-discovery import-results \
    --db "$DB_PATH" \
    --input-dir "$OUTPUT_DIR" || exit 1

echo "Pipeline complete. Results in ${DB_PATH}"

# EXIT trap fires — server killed

#!/usr/bin/env bash
# Container entrypoint — orchestrates vLLM server + llm-discovery pipeline.
#
# Replicates the pattern from scripts/process_corpus.sh but adapted for
# container execution:
#   - Background process instead of tmux (no tmux in container)
#   - Direct CLI calls instead of uv run (packages in /opt/venv)
#   - Only GPU stages (process + import-results), not prep-db/preflight
#   - Hardcoded /data/ paths from bind mounts
#
# Bind mounts:
#   --bind <data-dir>:/data        — must contain:
#     hpc_env.sh        — runtime config (VLLM_MODEL, VLLM_TP, VLLM_GPU_MEM, VLLM_MAX_SEQS)
#     corpus.db         — pre-built by prep-db on the host
#     system_prompt.txt — LLM extraction instructions (loaded by process command from cwd)
#     prompts/          — YAML category definitions (loaded relative to corpus.db parent)
#     out/              — created by this script for JSON results and vLLM logs
#   --bind ~/.cache/huggingface:/model_cache --env HF_HOME=/model_cache
#     HF model weights. Do NOT bind to /root/.cache/huggingface — Apptainer
#     runs as the calling user, not root, so $HOME differs from the Docker base.
#
# Required env vars (set in hpc_env.sh): VLLM_MODEL, VLLM_TP, VLLM_GPU_MEM, VLLM_MAX_SEQS
# Optional: VLLM_PORT (default: 8000), VLLM_MAX_MODEL_LEN

# Do NOT set -e — EXIT trap MUST always fire for server cleanup
# (matches scripts/process_corpus.sh design decision)

# --- 1. Source runtime configuration ---
if [ ! -f /data/hpc_env.sh ]; then
    echo "ERROR: /data/hpc_env.sh not found. Bind-mount a data directory containing hpc_env.sh."
    exit 1
fi
# shellcheck source=/dev/null
source /data/hpc_env.sh

# --- 2. Validate required env vars (pattern from scripts/start_server.sh) ---
for var in VLLM_MODEL VLLM_TP VLLM_GPU_MEM VLLM_MAX_SEQS; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: Required environment variable $var is not set in /data/hpc_env.sh"
        exit 1
    fi
done

VLLM_PORT="${VLLM_PORT:-8000}"

echo "============================================================"
echo "LLM Discovery Pipeline — Container Entrypoint"
echo "============================================================"
echo "Model:              $VLLM_MODEL"
echo "Port:               $VLLM_PORT"
echo "Tensor parallel:    $VLLM_TP"
echo "GPU memory util:    $VLLM_GPU_MEM"
echo "Max sequences:      $VLLM_MAX_SEQS"
echo "Max model len:      ${VLLM_MAX_MODEL_LEN:-default}"
echo ""

# --- 3. Build vllm serve command (pattern from scripts/start_server.sh) ---
CMD=(vllm serve "$VLLM_MODEL"
    --tensor-parallel-size "$VLLM_TP"
    --gpu-memory-utilization "$VLLM_GPU_MEM"
    --max-num-seqs "$VLLM_MAX_SEQS"
    --port "$VLLM_PORT"
    --trust-remote-code
)

if [ -n "${VLLM_MAX_MODEL_LEN:-}" ]; then
    CMD+=(--max-model-len "$VLLM_MAX_MODEL_LEN")
fi

if [ -n "${VLLM_DP:-}" ] && [ "$VLLM_DP" -gt 1 ] 2>/dev/null; then
    CMD+=(--data-parallel-size "$VLLM_DP")
fi

# --- 4. Launch vLLM as background process, log to /data/out/ ---
mkdir -p /data/out
"${CMD[@]}" > /data/out/vllm.log 2>&1 &
VLLM_PID=$!

# --- 5. EXIT trap — kill vLLM on any exit (pattern from scripts/process_corpus.sh) ---
cleanup() {
    echo "Cleaning up: killing vLLM server (PID $VLLM_PID)..."
    kill "$VLLM_PID" 2>/dev/null
    wait "$VLLM_PID" 2>/dev/null
    echo "Cleanup complete."
}
trap cleanup EXIT

# --- 6. Wait for server health (3600s timeout, 5s interval — from scripts/process_corpus.sh) ---
echo "Waiting for vLLM server on port ${VLLM_PORT}..."
MAX_WAIT=3600
WAITED=0
while ! curl -sf "http://localhost:${VLLM_PORT}/health" > /dev/null 2>&1; do
    # Check if vLLM process died
    if ! kill -0 "$VLLM_PID" 2>/dev/null; then
        echo "ERROR: vLLM server process died. Check /data/out/vllm.log"
        exit 1
    fi
    sleep 5
    WAITED=$((WAITED + 5))
    if [ "$WAITED" -ge "$MAX_WAIT" ]; then
        echo "ERROR: vLLM server did not start within ${MAX_WAIT}s"
        exit 1
    fi
done
echo "vLLM server is healthy (waited ${WAITED}s)"

# --- 7. Run GPU pipeline stages ---
# Only process + import-results run inside the container.
# prep-db and preflight run on the host before container launch.
#
# cd to /data so that:
#   - system_prompt.txt is found (process loads from cwd via Path("system_prompt.txt"))
#   - prompts/ resolves correctly (defaults to db_path.parent / "prompts")
#
# CLI parameter names verified from src/llm_discovery/cli.py:
#   process: --db, --output-dir, --server-url, --model
#   import-results: --db, --input-dir

cd /data || exit 1

llm-discovery process \
    --db /data/corpus.db \
    --output-dir /data/out \
    --server-url "http://localhost:${VLLM_PORT}" \
    --model "$VLLM_MODEL" \
    --concurrency "$VLLM_MAX_SEQS" || exit 1

llm-discovery import-results \
    --db /data/corpus.db \
    --input-dir /data/out || exit 1

echo "Pipeline complete. Results in /data/out/ and /data/corpus.db"

# EXIT trap fires — vLLM killed

#!/bin/bash
# Unattended corpus processing: start server, process, shutdown
#
# This script:
# 1. Initialises/syncs database (prep_db.py)
# 2. Starts vLLM server in background
# 3. Waits for server to be ready
# 4. Runs process_corpus.sh
# 5. Shuts down server when complete (success or failure)
#
# Usage:
#   bash run_unattended.sh
#
# Environment variables (inherited by sub-scripts):
#   MODEL          - Model name (default: openai/gpt-oss-120b)
#   MAX_NUM_SEQS   - Server batch size (default: 384)
#   TENSOR_PARALLEL - GPU count (default: 2)
#   CONCURRENCY    - Client concurrency (default: 384)
#   LIMIT          - Process limit (default: unlimited)
#   INPUT_DIR      - Corpus input directory (default: ./input/markdown_corpus)
#   DB_PATH        - Database path (default: ./corpus.db)
#
# For different corpora, set INPUT_DIR and DB_PATH in hpc_setup.sh:
#   export INPUT_DIR="$WORK_DIR/input/kidlink_corpus"
#   export DB_PATH="$WORK_DIR/corpus_kidlink.db"
set -euo pipefail

# Hardcoded default - portal execution may break BASH_SOURCE
SCRIPT_DIR="${WORK_DIR:-/work/20251104-FirstRun}"
cd "$SCRIPT_DIR" || { echo "ERROR: Cannot cd to $SCRIPT_DIR"; exit 1; }

# Source environment variables (corpus config, cache paths, etc.)
# This ensures batch jobs get the same config as interactive runs
if [ -f "$SCRIPT_DIR/hpc_env.sh" ]; then
    source "$SCRIPT_DIR/hpc_env.sh"
fi

# Ensure cache goes to /scratch (ephemeral), not /work/ (persistent)
export HF_HOME="${HF_HOME:-/scratch/cache/huggingface}"
export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-/scratch/cache/huggingface/hub}"
export VLLM_CACHE_ROOT="${VLLM_CACHE_ROOT:-/scratch/cache/vllm}"
export TORCH_HOME="${TORCH_HOME:-/scratch/cache/torch}"

# Verify script integrity - print hashes for comparison with local machine
echo "## Script Integrity Check (run_unattended.sh)"
echo "SCRIPT_DIR: $SCRIPT_DIR"
echo "pwd: $(pwd)"
echo "HF_HOME: $HF_HOME"
echo "SHA256 hashes:"
sha256sum "$SCRIPT_DIR"/{hpc_setup.sh,run_unattended.sh,process_corpus.sh,start_server_hpc.sh,runner.sh} 2>/dev/null || echo "(some shell scripts not found)"
sha256sum "$SCRIPT_DIR"/{unified_processor.py,prep_db.py,preflight_check.py,import_results.py} 2>/dev/null || echo "(some Python scripts not found)"
echo ""

# Default to 120b model
export MODEL="${MODEL:-openai/gpt-oss-120b}"
PORT="${PORT:-8000}"
SERVER_URL="http://localhost:$PORT"
SERVER_PID=""
LOG_FILE="$SCRIPT_DIR/vllm_server.log"

# Cleanup function - always runs on exit
cleanup() {
    if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        echo ""
        echo "[$(date +%H:%M:%S)] Shutting down vLLM server (PID $SERVER_PID)..."
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
        echo "[$(date +%H:%M:%S)] Server stopped"
    fi
}

trap cleanup EXIT

# Corpus configuration
# These should be set by hpc_setup.sh or environment. Defaults for backwards compatibility.
INPUT_DIR="${INPUT_DIR:-$SCRIPT_DIR/input/markdown_corpus}"
DB_PATH="${DB_PATH:-$SCRIPT_DIR/corpus.db}"
export INPUT_DIR
export DB_PATH

echo "============================================================"
echo "Unattended Corpus Processing"
echo "============================================================"
echo "Model: $MODEL"
echo "Input dir: $INPUT_DIR"
echo "Database: $DB_PATH"
echo "Server log: $LOG_FILE"
echo ""

# Step 1: Initialise/sync database
echo "[$(date +%H:%M:%S)] Initialising database..."
uv run python "$SCRIPT_DIR/prep_db.py" --db "$DB_PATH" --input-dir "$INPUT_DIR" --quiet
echo ""

# Step 2: Start server in background
echo "[$(date +%H:%M:%S)] Starting vLLM server..."
bash "$SCRIPT_DIR/start_server_hpc.sh" > "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "[$(date +%H:%M:%S)] Server started (PID $SERVER_PID)"

# Step 3: Wait for server to be ready (model download can take a while)
echo "[$(date +%H:%M:%S)] Waiting for server to be ready..."
echo "                     (model download may take 10-30 minutes on first run)"
MAX_WAIT=3600  # 1 hour max (model download can be slow)
WAITED=0

while [ $WAITED -lt $MAX_WAIT ]; do
    # Check if server process died
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
        echo ""
        echo "ERROR: Server process died. Check $LOG_FILE for details."
        echo "Last 20 lines:"
        tail -20 "$LOG_FILE"
        exit 1
    fi

    # Check if server is responding
    if curl -s "$SERVER_URL/health" >/dev/null 2>&1; then
        echo "[$(date +%H:%M:%S)] Server ready (waited $WAITED seconds)"
        break
    fi

    sleep 10
    WAITED=$((WAITED + 10))

    # Show progress every minute
    if [ $((WAITED % 60)) -eq 0 ]; then
        echo "[$(date +%H:%M:%S)] Still waiting... ($((WAITED / 60)) minutes)"
        # Show last line of log for progress indication
        tail -1 "$LOG_FILE" 2>/dev/null | head -c 100
        echo ""
    fi
done

if [ $WAITED -ge $MAX_WAIT ]; then
    echo ""
    echo "ERROR: Server did not become ready within $((MAX_WAIT / 60)) minutes"
    echo "Last 20 lines of log:"
    tail -20 "$LOG_FILE"
    exit 1
fi

echo ""

# Step 4: Run processing
echo "[$(date +%H:%M:%S)] Starting corpus processing..."
export SERVER_URL
export SKIP_SYNC=1  # prep_db already synced in Step 1, avoid OOM with server running
bash "$SCRIPT_DIR/process_corpus.sh"
PROCESS_EXIT=$?

echo ""
if [ $PROCESS_EXIT -eq 0 ]; then
    echo "[$(date +%H:%M:%S)] Processing completed successfully"
else
    echo "[$(date +%H:%M:%S)] Processing failed with exit code $PROCESS_EXIT"
fi

# Cleanup happens automatically via trap
exit $PROCESS_EXIT

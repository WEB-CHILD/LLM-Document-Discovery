#!/bin/bash
# HPC Runner - Entry point for corpus processing
#
# Architecture: Streaming with JSON file output
# - Workers write individual JSON files to OUTPUT_DIR
# - Crash-safe: atomic file writes (temp + rename)
# - Resumable: imports existing JSON files at start, skips completed pairs
#
# Prerequisites:
#   1. Start vLLM server in another terminal:
#      bash start_server_hpc.sh
#
#   2. Run this script:
#      bash runner.sh

set -euo pipefail

# Hardcoded default - portal execution may break BASH_SOURCE
SCRIPT_DIR="${WORK_DIR:-/work/20251104-FirstRun}"
cd "$SCRIPT_DIR" || { echo "ERROR: Cannot cd to $SCRIPT_DIR"; exit 1; }

# Model configuration
MODEL="${MODEL:-openai/gpt-oss-120b}"

# Database path (for reading pairs)
DB_PATH="${DB_PATH:-/work/20251104-FirstRun/corpus.db}"

# Output directory for JSON files
OUTPUT_DIR="${OUTPUT_DIR:-/work/20251104-FirstRun/out}"

# Server configuration (validated optimal settings from Elaboration07)
SERVER_URL="${SERVER_URL:-http://localhost:8000}"
CONCURRENCY="${CONCURRENCY:-128}"

# Optional: limit pairs to process (leave empty for all)
LIMIT="${LIMIT:-}"

# Build limit argument
LIMIT_ARG=""
if [ -n "$LIMIT" ]; then
    LIMIT_ARG="--limit $LIMIT"
fi

echo "============================================================"
echo "Corpus Processor (Streaming + JSON)"
echo "============================================================"
echo "Database: $DB_PATH"
echo "Output:   $OUTPUT_DIR"
echo "Server:   $SERVER_URL"
echo "Workers:  $CONCURRENCY"
echo "Limit:    ${LIMIT:-unlimited}"
echo ""

# Step 1: Import any existing JSON files (resume from previous runs)
echo "Step 1: Importing existing results from $OUTPUT_DIR..."
if [ -d "$OUTPUT_DIR" ] && ls "$OUTPUT_DIR"/r*_c*.json >/dev/null 2>&1; then
    uv run python import_results.py --db "$DB_PATH" --input-dir "$OUTPUT_DIR"
else
    echo "  No existing JSON files found, starting fresh."
fi
echo ""

# Step 2: Wait for vLLM server to be ready
echo "Step 2: Waiting for vLLM server..."
until curl -sf "${SERVER_URL}/health" > /dev/null 2>&1; do
    echo "  Server not ready, retrying in 5s..."
    sleep 5
done
echo "Server is ready."
echo ""

# Step 3: Process corpus
echo "Step 3: Processing corpus..."
# shellcheck disable=SC2086
uv run python unified_processor.py \
    --db "$DB_PATH" \
    --output-dir "$OUTPUT_DIR" \
    --server-url "$SERVER_URL" \
    --concurrency "$CONCURRENCY" \
    --model "$MODEL" \
    $LIMIT_ARG

echo ""

# Step 4: Import new results to SQLite
echo "Step 4: Importing results to SQLite..."
uv run python import_results.py --db "$DB_PATH" --input-dir "$OUTPUT_DIR"

echo ""
echo "============================================================"
echo "Processing complete."
echo "============================================================"
echo "  JSON files: $OUTPUT_DIR"
echo "  Database:   $DB_PATH"
echo ""
echo "To view results:"
echo "  datasette $DB_PATH"
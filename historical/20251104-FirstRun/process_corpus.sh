#!/bin/bash
# Orchestration script for full corpus processing pipeline
#
# This script:
# 1. Runs pre-flight check on database
# 2. Runs unified_processor.py (direct DB-to-vLLM-to-DB streaming)
# 3. Shows final statistics
#
# Supports resumability - rerun after crash/timeout to continue processing
#
# NOTE: Requires vLLM server to be running. Start with:
#   bash start_server_hpc.sh

set -euo pipefail

# Configuration - hardcoded default for portal execution
SCRIPT_DIR="${WORK_DIR:-/work/20251104-FirstRun}"
DB_PATH="${DB_PATH:-$SCRIPT_DIR/corpus.db}"
MODEL="${MODEL:-openai/gpt-oss-120b}"
LIMIT="${LIMIT:-}"  # Empty = process all
SERVER_URL="${SERVER_URL:-http://localhost:8000}"
CONCURRENCY="${CONCURRENCY:-384}"
OUTPUT_DIR="${OUTPUT_DIR:-$SCRIPT_DIR/out}"

echo "============================================================"
echo "Full Corpus Processing Pipeline"
echo "============================================================"
echo "Project root: $SCRIPT_DIR"
echo "Database: $DB_PATH"
echo "Model: $MODEL"
echo "Server: $SERVER_URL"
echo "Concurrency: $CONCURRENCY"
echo "Output dir: $OUTPUT_DIR"
echo "Limit: ${LIMIT:-unlimited}"
echo ""

# Step 0: Pre-flight database check
echo "============================================================"
echo "Step 0: Pre-flight Database Check"
echo "============================================================"
echo "[$(date +%H:%M:%S)] Scanning for problematic documents..."

uv run python "$SCRIPT_DIR/preflight_check.py" --db "$DB_PATH" --delete

PREFLIGHT_EXIT=$?
if [ $PREFLIGHT_EXIT -ne 0 ]; then
    echo ""
    echo "✗ Pre-flight check failed with exit code $PREFLIGHT_EXIT"
    exit $PREFLIGHT_EXIT
fi

echo "[$(date +%H:%M:%S)] Pre-flight check complete"
echo ""

# Step 1: Import existing JSON files (for resumability)
echo "============================================================"
echo "Step 1: Import Existing Results"
echo "============================================================"
echo "[$(date +%H:%M:%S)] Importing any existing JSON files from $OUTPUT_DIR..."

# Only run import if output dir exists and has JSON files
if [ -d "$OUTPUT_DIR" ] && ls "$OUTPUT_DIR"/r*_c*.json 1>/dev/null 2>&1; then
    uv run python "$SCRIPT_DIR/import_results.py" --db "$DB_PATH" --input-dir "$OUTPUT_DIR"
    echo "[$(date +%H:%M:%S)] Import complete"
else
    echo "[$(date +%H:%M:%S)] No existing JSON files to import"
fi
echo ""

# Step 2: Process with unified processor (direct DB streaming)
echo "============================================================"
echo "Step 2: Process Corpus"
echo "============================================================"
echo "[$(date +%H:%M:%S)] Starting unified processor..."

# SKIP_SYNC=1 set by run_unattended.sh (prep_db synced before server started).
# This avoids OOM: sync is memory-intensive and fails when vLLM has loaded model.
SKIP_SYNC_FLAG=""
if [ "${SKIP_SYNC:-0}" = "1" ]; then
    SKIP_SYNC_FLAG="--skip-sync"
    echo "[$(date +%H:%M:%S)] Skipping sync (prep_db already ran)"
fi

PROCESSOR_CMD="uv run python $SCRIPT_DIR/unified_processor.py --db $DB_PATH --output-dir $OUTPUT_DIR --server-url $SERVER_URL --concurrency $CONCURRENCY --model $MODEL $SKIP_SYNC_FLAG"

if [ -n "$LIMIT" ]; then
    PROCESSOR_CMD="$PROCESSOR_CMD --limit $LIMIT"
fi

echo "Running: $PROCESSOR_CMD"
echo ""

eval "$PROCESSOR_CMD"

PROCESSOR_EXIT=$?
echo "[$(date +%H:%M:%S)] Processor completed with exit code: $PROCESSOR_EXIT"

if [ "$PROCESSOR_EXIT" -ne 0 ]; then
    echo ""
    echo "✗ Processor failed with exit code $PROCESSOR_EXIT"
    echo ""
    echo "Recovery options:"
    echo "  1. Check vLLM server logs"
    echo "  2. Rerun this script to resume (completed pairs are skipped)"
    exit "$PROCESSOR_EXIT"
fi

echo ""

# Step 3: Import new results
echo "============================================================"
echo "Step 3: Import New Results"
echo "============================================================"
echo "[$(date +%H:%M:%S)] Importing newly processed JSON files..."

if [ -d "$OUTPUT_DIR" ] && ls "$OUTPUT_DIR"/r*_c*.json 1>/dev/null 2>&1; then
    uv run python "$SCRIPT_DIR/import_results.py" --db "$DB_PATH" --input-dir "$OUTPUT_DIR"
    echo "[$(date +%H:%M:%S)] Import complete"
else
    echo "[$(date +%H:%M:%S)] No JSON files to import"
fi
echo ""

# Step 4: Show final statistics
echo "============================================================"
echo "Step 4: Final Statistics"
echo "============================================================"

sqlite3 "$DB_PATH" <<EOF
SELECT
    'Total documents: ' || COUNT(*)
FROM result;

SELECT
    'Total categories: ' || COUNT(*)
FROM category;

SELECT 'Processed pairs: ' || COUNT(*) FROM result_category;
SELECT 'Total possible: ' || (SELECT COUNT(*) FROM result) * (SELECT COUNT(*) FROM category);

SELECT
    'Total blockquotes: ' || COUNT(*)
FROM result_category_blockquote;
EOF

echo ""
echo "============================================================"
echo "✓ Pipeline Complete"
echo "============================================================"
echo "Database: $DB_PATH"
echo ""
echo "To view results:"
echo "  datasette $DB_PATH"
echo ""
echo "To resume processing:"
echo "  bash $0"
echo ""

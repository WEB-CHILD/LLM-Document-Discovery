#!/bin/bash
# Orchestration script for full corpus processing pipeline
#
# This script:
# 1. Generates batch file (sync categories, documents, find missing pairs)
# 2. Runs vLLM batch processing with timing
# 3. Inserts results into database
# 4. Shows final statistics
#
# Supports resumability - rerun after crash/timeout to continue processing

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DB_PATH="${DB_PATH:-$PROJECT_ROOT/corpus.db}"
MODEL="${MODEL:-openai/gpt-oss-20b}"
LIMIT="${LIMIT:-}"  # Empty = process all documents

# File paths
BATCH_FILE="$SCRIPT_DIR/batch.jsonl"
RESULTS_FILE="$SCRIPT_DIR/results.jsonl"

echo "============================================================"
echo "Full Corpus Processing Pipeline"
echo "============================================================"
echo "Project root: $PROJECT_ROOT"
echo "Database: $DB_PATH"
echo "Model: $MODEL"
echo "Document limit: ${LIMIT:-unlimited}"
echo ""

# Step 1: Generate batch file
echo "============================================================"
echo "Step 1: Generate Batch File"
echo "============================================================"

GENERATE_CMD="uv run python $SCRIPT_DIR/generate_batch_full.py --output $BATCH_FILE --db $DB_PATH --model $MODEL"

if [ -n "$LIMIT" ]; then
    GENERATE_CMD="$GENERATE_CMD --limit $LIMIT"
fi

echo "Running: $GENERATE_CMD"
echo ""

eval "$GENERATE_CMD"

GENERATE_EXIT=$?

if [ $GENERATE_EXIT -ne 0 ]; then
    echo ""
    echo "✗ Batch generation failed with exit code $GENERATE_EXIT"
    exit $GENERATE_EXIT
fi

# Check if batch file has any requests
if [ ! -f "$BATCH_FILE" ]; then
    echo ""
    echo "✗ Batch file not created: $BATCH_FILE"
    exit 1
fi

NUM_REQUESTS=$(wc -l < "$BATCH_FILE")

if [ $NUM_REQUESTS -eq 0 ]; then
    echo ""
    echo "✓ No requests to process (all pairs already completed)"
    exit 0
fi

echo ""
echo "✓ Batch file ready: $NUM_REQUESTS requests"
echo ""

# Step 2: Run vLLM batch processing
echo "============================================================"
echo "Step 2: Run vLLM Batch Processing"
echo "============================================================"

bash "$SCRIPT_DIR/run_batch_timed.sh" "$BATCH_FILE" "$MODEL" "$RESULTS_FILE"

VLLM_EXIT=$?

if [ $VLLM_EXIT -ne 0 ]; then
    echo ""
    echo "✗ vLLM batch processing failed with exit code $VLLM_EXIT"
    echo ""
    echo "Recovery options:"
    echo "  1. Check vLLM logs for errors"
    echo "  2. Rerun this script to resume from last commit"
    echo "  3. Partial results (if any) are in: $RESULTS_FILE"
    exit $VLLM_EXIT
fi

# Check if results file was created
if [ ! -f "$RESULTS_FILE" ]; then
    echo ""
    echo "✗ Results file not created: $RESULTS_FILE"
    exit 1
fi

NUM_RESULTS=$(wc -l < "$RESULTS_FILE")

if [ $NUM_RESULTS -eq 0 ]; then
    echo ""
    echo "✗ No results written to results file"
    exit 1
fi

echo ""
echo "✓ vLLM processing complete: $NUM_RESULTS results"
echo ""

# Step 3: Insert results into database
echo "============================================================"
echo "Step 3: Insert Results into Database"
echo "============================================================"

uv run python "$SCRIPT_DIR/batch_to_db.py" "$RESULTS_FILE" "$DB_PATH"

DB_EXIT=$?

if [ $DB_EXIT -ne 0 ]; then
    echo ""
    echo "✗ Database insertion failed with exit code $DB_EXIT"
    exit $DB_EXIT
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

SELECT
    'Processed pairs: ' || COUNT(*) || ' / ' ||
    (SELECT COUNT(*) FROM result) * (SELECT COUNT(*) FROM category) ||
    ' (' || ROUND(CAST(COUNT(*) AS REAL) / ((SELECT COUNT(*) FROM result) * (SELECT COUNT(*) FROM category)) * 100, 1) || '%)'
FROM result_category;

SELECT
    'Total blockquotes: ' || COUNT(*)
FROM result_category_blockquote;

SELECT
    'Match distribution:'
UNION ALL
SELECT
    '  ' || match || ': ' || COUNT(*)
FROM result_category
GROUP BY match
ORDER BY match;
EOF

echo ""
echo "============================================================"
echo "✓ Pipeline Complete"
echo "============================================================"
echo "Database: $DB_PATH"
echo "Timing data: ${RESULTS_FILE%.jsonl}_timing.txt"
echo ""
echo "To view results:"
echo "  datasette $DB_PATH"
echo ""
echo "To resume processing:"
echo "  bash $0"
echo ""

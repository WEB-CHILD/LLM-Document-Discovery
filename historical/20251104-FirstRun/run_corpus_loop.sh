#!/bin/bash
# Loop-based corpus processing with automatic checkpointing
#
# Processes corpus in small batches, committing after each iteration.
# Fully resumable - can be stopped/restarted at any time.

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_PATH="${DB_PATH:-$SCRIPT_DIR/corpus.db}"
MODEL="${MODEL:-openai/gpt-oss-120b}"
BATCH_SIZE="${BATCH_SIZE:-8}"       # Documents per iteration (~10,500 requests at 21 categories)
MAX_ITERATIONS="${MAX_ITERATIONS:-}"  # Empty = run until complete

ITERATION=0
TOTAL_PROCESSED=0

echo "============================================================"
echo "Corpus Processing Loop"
echo "============================================================"
echo "Database: $DB_PATH"
echo "Model: $MODEL"
echo "Batch size: $BATCH_SIZE documents per iteration"
echo "Max iterations: ${MAX_ITERATIONS:-unlimited}"
echo "Started: $(date)"
echo ""

while true; do
    ITERATION=$((ITERATION + 1))

    echo "============================================================"
    echo "Iteration $ITERATION - $(date)"
    echo "============================================================"

    # Check how many pairs remain
    echo "[$(date +%H:%M:%S)] Checking remaining documents..."
    if [ -f "$DB_PATH" ]; then
        REMAINING=$(sqlite3 "$DB_PATH" "
            SELECT COUNT(*) FROM (
                SELECT DISTINCT r.result_id
                FROM result r
                CROSS JOIN category c
                WHERE NOT EXISTS (
                    SELECT 1 FROM result_category rc
                    WHERE rc.result_id = r.result_id
                    AND rc.category_id = c.category_id
                )
            )
        " 2>/dev/null || echo "0")

        echo "[$(date +%H:%M:%S)] Documents with incomplete processing: $REMAINING"

        if [ "$REMAINING" -eq 0 ]; then
            echo ""
            echo "✓ All documents processed!"
            break
        fi
    fi

    # Run one batch
    echo "[$(date +%H:%M:%S)] Starting batch processing of $BATCH_SIZE documents..."
    echo ""

    LIMIT=$BATCH_SIZE bash "$SCRIPT_DIR/process_corpus.sh"

    EXIT_CODE=$?
    echo ""
    echo "[$(date +%H:%M:%S)] Batch processing returned with exit code: $EXIT_CODE"

    if [ $EXIT_CODE -ne 0 ]; then
        echo ""
        echo "⚠ Iteration $ITERATION failed with exit code $EXIT_CODE"
        echo "Database has been updated with any completed work"
        echo "You can rerun this script to resume from where it stopped"
        exit $EXIT_CODE
    fi

    # Count how many we've done
    if [ -f "$DB_PATH" ]; then
        DOCS_PROCESSED=$(sqlite3 "$DB_PATH" "
            SELECT COUNT(DISTINCT result_id) FROM result_category
        " 2>/dev/null || echo "0")

        BATCH_PROCESSED=$((DOCS_PROCESSED - TOTAL_PROCESSED))
        TOTAL_PROCESSED=$DOCS_PROCESSED

        echo ""
        echo "✓ Iteration $ITERATION complete"
        echo "  This batch: $BATCH_PROCESSED documents"
        echo "  Total: $TOTAL_PROCESSED documents"
    fi

    # Check max iterations
    if [ -n "$MAX_ITERATIONS" ] && [ "$ITERATION" -ge "$MAX_ITERATIONS" ]; then
        echo ""
        echo "Reached maximum iterations ($MAX_ITERATIONS)"
        echo "Progress saved. Rerun without MAX_ITERATIONS to continue."
        break
    fi

    echo ""
done

echo ""
echo "============================================================"
echo "Processing Complete"
echo "============================================================"
echo "Total iterations: $ITERATION"
echo "Total documents processed: $TOTAL_PROCESSED"
echo "Ended: $(date)"
echo ""

# Final statistics
if [ -f "$DB_PATH" ]; then
    sqlite3 "$DB_PATH" <<EOF
.mode line
SELECT
    'Total documents' as metric,
    COUNT(*) as value
FROM result
UNION ALL
SELECT
    'Total categories',
    COUNT(*)
FROM category
UNION ALL
SELECT
    'Processed pairs',
    COUNT(*)
FROM result_category
UNION ALL
SELECT
    'Total blockquotes',
    COUNT(*)
FROM result_category_blockquote;
EOF
fi

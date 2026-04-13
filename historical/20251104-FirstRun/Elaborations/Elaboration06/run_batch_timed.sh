#!/bin/bash
# Run vLLM batch with timing data collection

set -euo pipefail

# Usage check
if [ $# -lt 1 ]; then
    echo "Usage: $0 <batch.jsonl> [model] [output.jsonl]"
    echo ""
    echo "Example:"
    echo "  $0 batch.jsonl openai/gpt-oss-20b results.jsonl"
    exit 1
fi

BATCH_FILE="$1"
MODEL="${2:-openai/gpt-oss-20b}"
OUTPUT_FILE="${3:-results.jsonl}"

# Validate batch file exists
if [ ! -f "$BATCH_FILE" ]; then
    echo "Error: Batch file not found: $BATCH_FILE"
    exit 1
fi

# Count requests
NUM_REQUESTS=$(wc -l < "$BATCH_FILE")

echo "============================================================"
echo "vLLM Batch Processing with Timing"
echo "============================================================"
echo "Batch file: $BATCH_FILE"
echo "Model: $MODEL"
echo "Output file: $OUTPUT_FILE"
echo "Requests: $NUM_REQUESTS"
echo ""

# Record start time
START_TIME=$(date +%s)
START_TIME_HR=$(date '+%Y-%m-%d %H:%M:%S')

echo "Start time: $START_TIME_HR"
echo ""

# Run batch processing
echo "Running vLLM batch..."
echo ""

uv run vllm run-batch \
    --input-file "$BATCH_FILE" \
    --output-file "$OUTPUT_FILE" \
    --model "$MODEL" \
    --tensor-parallel-size 2 \
    --gpu-memory-utilization 0.95 \
    --max-num-seqs 15

EXIT_CODE=$?

# Record end time
END_TIME=$(date +%s)
END_TIME_HR=$(date '+%Y-%m-%d %H:%M:%S')

# Calculate duration
DURATION=$((END_TIME - START_TIME))
HOURS=$((DURATION / 3600))
MINUTES=$(((DURATION % 3600) / 60))
SECONDS=$((DURATION % 60))

echo ""
echo "============================================================"
echo "Timing Summary"
echo "============================================================"
echo "Start time: $START_TIME_HR"
echo "End time: $END_TIME_HR"
echo "Duration: ${HOURS}h ${MINUTES}m ${SECONDS}s (${DURATION} seconds)"
echo "Requests: $NUM_REQUESTS"

if [ -f "$OUTPUT_FILE" ]; then
    RESULTS_COUNT=$(wc -l < "$OUTPUT_FILE")
    echo "Results written: $RESULTS_COUNT"

    if [ $RESULTS_COUNT -gt 0 ]; then
        REQ_PER_SEC=$(echo "scale=2; $RESULTS_COUNT / $DURATION" | bc)
        SEC_PER_REQ=$(echo "scale=2; $DURATION / $RESULTS_COUNT" | bc)
        echo "Throughput: ${REQ_PER_SEC} requests/second"
        echo "Latency: ${SEC_PER_REQ} seconds/request"
    fi
else
    echo "Results written: 0 (output file not found)"
fi

echo "Exit code: $EXIT_CODE"
echo ""

# Write timing data to file
TIMING_FILE="${OUTPUT_FILE%.jsonl}_timing.txt"
cat > "$TIMING_FILE" <<EOF
vLLM Batch Processing Timing Report
====================================

Batch file: $BATCH_FILE
Model: $MODEL
Output file: $OUTPUT_FILE

Start time: $START_TIME_HR ($START_TIME)
End time: $END_TIME_HR ($END_TIME)
Duration: ${HOURS}h ${MINUTES}m ${SECONDS}s (${DURATION} seconds)

Requests: $NUM_REQUESTS
Results: ${RESULTS_COUNT:-0}
Exit code: $EXIT_CODE

EOF

if [ -f "$OUTPUT_FILE" ] && [ ${RESULTS_COUNT:-0} -gt 0 ]; then
    REQ_PER_SEC=$(echo "scale=2; $RESULTS_COUNT / $DURATION" | bc)
    SEC_PER_REQ=$(echo "scale=2; $DURATION / $RESULTS_COUNT" | bc)
    cat >> "$TIMING_FILE" <<EOF
Throughput: ${REQ_PER_SEC} requests/second
Latency: ${SEC_PER_REQ} seconds/request
EOF
fi

echo "Timing data saved to: $TIMING_FILE"

exit $EXIT_CODE

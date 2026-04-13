#!/bin/bash
# Run vLLM batch with timing data collection

set -euo pipefail

# Usage check
if [ $# -lt 1 ]; then
    echo "Usage: $0 <batch.jsonl> [model] [output.jsonl]"
    echo ""
    echo "Example:"
    echo "  $0 batch.jsonl openai/gpt-oss-120b results.jsonl"
    exit 1
fi

BATCH_FILE="$1"
MODEL="${2:-openai/gpt-oss-120b}"
OUTPUT_FILE="${3:-results.jsonl}"

# Validate batch file exists
if [ ! -f "$BATCH_FILE" ]; then
    echo "Error: Batch file not found: $BATCH_FILE"
    exit 1
fi

# Detect number of available GPUs
if command -v nvidia-smi &> /dev/null; then
    GPU_COUNT=$(nvidia-smi --query-gpu=name --format=csv,noheader | wc -l)
else
    GPU_COUNT=1
fi

# Calculate optimal vLLM parameters based on model
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/calculate_vllm_params.py" ]; then
    eval "$(uv run python "$SCRIPT_DIR/calculate_vllm_params.py" "$MODEL" --gpus "$GPU_COUNT" 2>/dev/null | grep '^export')"
fi

# Allow manual overrides
TENSOR_PARALLEL_SIZE="${TENSOR_PARALLEL_SIZE:-1}"
DATA_PARALLEL_SIZE="${DATA_PARALLEL_SIZE:-1}"
PIPELINE_PARALLEL_SIZE="${PIPELINE_PARALLEL_SIZE:-1}"
# MAX_NUM_SEQS="${MAX_NUM_SEQS:-15}"

# Count requests
NUM_REQUESTS=$(wc -l < "$BATCH_FILE")

echo "============================================================"
echo "vLLM Batch Processing with Timing"
echo "============================================================"
echo "Batch file: $BATCH_FILE"
echo "Model: $MODEL"
echo "Output file: $OUTPUT_FILE"
echo "Requests: $NUM_REQUESTS"
echo "GPUs detected: $GPU_COUNT"
echo "Tensor parallel size: $TENSOR_PARALLEL_SIZE"
echo "Data parallel size: $DATA_PARALLEL_SIZE"
echo "Pipeline parallel size: $PIPELINE_PARALLEL_SIZE"
echo "Max sequences per replica: $MAX_NUM_SEQS"
echo "Total concurrent sequences: $((MAX_NUM_SEQS * DATA_PARALLEL_SIZE))"
echo ""



# Run batch processing
echo "[$(date +%H:%M:%S)] Running vLLM batch..."
echo ""

uv run vllm run-batch \
    --input-file "$BATCH_FILE" \
    --output-file "$OUTPUT_FILE" \
    --model "$MODEL" \
    --gpu-memory-utilization 0.90 \
    --max-num-seqs "$MAX_NUM_SEQS"
    # don't bother with these, gpu is tetchy
    # --data-parallel-size "$DATA_PARALLEL_SIZE"
    # --tensor-parallel-size "$TENSOR_PARALLEL_SIZE" \
    #  --pipeline-parallel-size "$PIPELINE_PARALLEL_SIZE"
    

EXIT_CODE=$?
echo ""
echo "[$(date +%H:%M:%S)] vLLM batch command completed with exit code: $EXIT_CODE"




exit $EXIT_CODE

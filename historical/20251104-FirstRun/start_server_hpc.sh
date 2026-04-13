#!/bin/bash
# Start vLLM Server for HPC
#
# Optimal settings validated in Elaboration07:
#   --max-num-seqs 256 with --concurrency 128 gives ~2 req/s per GPU
#   --tensor-parallel-size 2 for 2-GPU setup gives ~3 req/s
#
# Usage:
#   Single GPU:  bash start_server_hpc.sh
#   Two GPUs:    bash start_server_hpc.sh --tp 2
#   Custom seqs: bash start_server_hpc.sh 384

set -euo pipefail

MODEL="${MODEL:-openai/gpt-oss-120b}"
PORT="${PORT:-8000}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-384}"
TENSOR_PARALLEL="${TENSOR_PARALLEL:-2}"

# Hugging Face token for gated models
export HF_TOKEN="${HF_TOKEN:-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}"

# Logging - INFO by default, set DEBUG for startup troubleshooting
export VLLM_LOGGING_LEVEL="${VLLM_LOGGING_LEVEL:-INFO}"
export NCCL_DEBUG="${NCCL_DEBUG:-WARN}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --tp)
            TENSOR_PARALLEL="${2:-2}"
            shift 2
            ;;
        [0-9]*)
            MAX_NUM_SEQS="$1"
            shift
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

echo "============================================================"
echo "Starting vLLM Server (HPC)"
echo "============================================================"
echo "Model: $MODEL"
echo "Port: $PORT"
echo "Max sequences: $MAX_NUM_SEQS"
echo "Tensor parallel: $TENSOR_PARALLEL"
echo ""

# Check if port is already in use
if lsof -Pi :"$PORT" -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "ERROR: Port $PORT is already in use. Is the server already running?"
    exit 1
fi

echo "Starting server... (Press Ctrl+C to stop)"
echo "Logs will be shown below."
echo ""

if [ "$TENSOR_PARALLEL" -gt 1 ]; then
    # Multi-GPU with tensor parallelism
    uv run vllm serve "$MODEL" \
        --port "$PORT" \
        --gpu-memory-utilization 0.95 \
        --max-num-seqs "$MAX_NUM_SEQS" \
        --tensor-parallel-size "$TENSOR_PARALLEL"
else
    # Single GPU
    uv run vllm serve "$MODEL" \
        --port "$PORT" \
        --gpu-memory-utilization 0.95 \
        --max-num-seqs "$MAX_NUM_SEQS"
fi

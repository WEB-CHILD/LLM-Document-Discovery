#!/bin/bash
# Start vLLM Server for Experiment
# Configured for stability on consumer hardware (e.g. RTX 5090)
#
# Usage:
#   bash start_server.sh

set -euo pipefail

MODEL="${MODEL:-openai/gpt-oss-120b}"
PORT="${PORT:-8000}"

echo "============================================================"
echo "Starting vLLM Server"
echo "============================================================"
echo "Model: $MODEL"
echo "Port: $PORT"
echo "Hardware config:"
echo "  --gpu-memory-utilization 0.85 (Reserve 15% for system/other apps)"
echo "  --swap-space 16 (16GB CPU swap for KV cache offloading)"
echo "  --max-num-seqs 8 (Limit concurrency to prevent OOM)"
echo ""

# Check if port is already in use
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null ; then
    echo "ERROR: Port $PORT is already in use. Is the server already running?"
    exit 1
fi

echo "Starting server... (Press Ctrl+C to stop)"
echo "Logs will be shown below."
echo ""

uv run vllm serve "$MODEL" \
    --port "$PORT" \
    --gpu-memory-utilization 0.85 \
    --max-num-seqs 8 \
    --swap-space 16

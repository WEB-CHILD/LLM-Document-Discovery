#!/usr/bin/env bash
# Start vLLM server with GPU-specific parameters.
# Reads configuration from environment variables (set by process_corpus.sh
# or HPC job scripts).
#
# Required env vars: VLLM_MODEL, VLLM_TP, VLLM_GPU_MEM, VLLM_MAX_SEQS
# Optional: VLLM_PORT (default: 8000), VLLM_MAX_MODEL_LEN (default: unset)

set -euo pipefail

VLLM_PORT="${VLLM_PORT:-8000}"

# Validate required variables
for var in VLLM_MODEL VLLM_TP VLLM_GPU_MEM VLLM_MAX_SEQS; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: Required environment variable $var is not set"
        exit 1
    fi
done

echo "============================================================"
echo "Starting vLLM Server"
echo "============================================================"
echo "Model:              $VLLM_MODEL"
echo "Port:               $VLLM_PORT"
echo "Tensor parallel:    $VLLM_TP"
echo "GPU memory util:    $VLLM_GPU_MEM"
echo "Max sequences:      $VLLM_MAX_SEQS"
echo "Max model len:      ${VLLM_MAX_MODEL_LEN:-default}"
echo ""

# Build command with optional arguments
CMD=(uv run vllm serve "$VLLM_MODEL"
    --tensor-parallel-size "$VLLM_TP"
    --gpu-memory-utilization "$VLLM_GPU_MEM"
    --max-num-seqs "$VLLM_MAX_SEQS"
    --port "$VLLM_PORT"
    --trust-remote-code
)

# Limit context length if specified (important for fitting on smaller GPUs)
if [ -n "${VLLM_MAX_MODEL_LEN:-}" ]; then
    CMD+=(--max-model-len "$VLLM_MAX_MODEL_LEN")
fi

# Skip multimodal profiling for text-only workloads
if [ "${VLLM_TEXT_ONLY:-}" = "1" ]; then
    CMD+=(--limit-mm-per-prompt "image=0,audio=0")
fi

exec "${CMD[@]}"

#!/usr/bin/env bash
# HPC environment variables for vLLM

export VLLM_BASE="/work/20251104-FirstRun/scratch"
export HF_HOME="$VLLM_BASE"
export HUGGINGFACE_HUB_CACHE="$VLLM_BASE/hub"
# export TRANSFORMERS_CACHE="$VLLM_BASE/transformers"
export VLLM_CACHE_ROOT="$VLLM_BASE/cache"
export UV_TORCH_BACKEND=auto
export UV_LINK_MODE=copy
export HF_TOKEN=REDACTED

# System update (quiet output, show only on failure)
echo "Updating system packages..."
if sudo apt update -y > /tmp/apt.log 2>&1 && \
   sudo apt upgrade -y >> /tmp/apt.log 2>&1 && \
   sudo apt install nvidia-cuda-toolkit -y >> /tmp/apt.log 2>&1; then
    echo "  ✓ System updated"
else
    echo "  ✗ apt failed:"
    cat /tmp/apt.log
fi

if ! which uv > /dev/null 2>&1; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh 2>/dev/null | sh > /dev/null 2>&1
fi


#!/usr/bin/env bash
#
# HPC Environment Variables
# Source this file to load environment variables in current shell:
#   source /work/20251104-FirstRun/hpc_env.sh
#

# Cache directories on /scratch (500GB available, regeneratable)
export VLLM_BASE="/scratch/cache/vllm"
export HF_HOME="/scratch/cache/huggingface"
export HUGGINGFACE_HUB_CACHE="/scratch/cache/huggingface/hub"
export VLLM_CACHE_ROOT="/scratch/cache/vllm"
export TORCH_HOME="/scratch/cache/torch"

# Virtual environment on /scratch
export UV_PROJECT_ENVIRONMENT="/scratch/venv"
export UV_TORCH_BACKEND=auto
export UV_LINK_MODE=copy

# Model configuration (can be overridden)
export GPT_MODEL="${GPT_MODEL:-openai/gpt-oss-120b}"
export VLLM_TENSOR_PARALLEL_SIZE="${VLLM_TENSOR_PARALLEL_SIZE:-1}"  # Single GPU (TP=2 has Ray initialization issues)
export VLLM_GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.98}"  # Dedicated GPU, can use 98%
export REASONING_EFFORT="${REASONING_EFFORT:-Medium}"

# Project paths
export WORK_DIR="/work/20251104-FirstRun"

# Corpus configuration - update these for different corpora:
#   kidlink_corpus  -> corpus_kidlink.db
#   markdown_corpus -> corpus_markdown.db
export CORPUS_NAME="kidlink_corpus"
export INPUT_DIR="$WORK_DIR/input/$CORPUS_NAME"
export DB_PATH="$WORK_DIR/corpus_kidlink.db"

# Add uv to PATH
export PATH="$HOME/.local/bin:$PATH"

# Confirm loaded
echo "✓ HPC environment variables loaded"
echo "  VLLM_BASE=$VLLM_BASE"
echo "  GPT_MODEL=$GPT_MODEL"
echo "  VLLM_TENSOR_PARALLEL_SIZE=$VLLM_TENSOR_PARALLEL_SIZE"

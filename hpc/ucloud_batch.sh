#!/usr/bin/env bash
# UCloud Terminal app batch script
# Run inside container with GPU access

# Set vLLM parameters for H100
export VLLM_MODEL="${VLLM_MODEL:-openai/gpt-oss-120b}"
export VLLM_TP=4
export VLLM_GPU_MEM=0.92
export VLLM_MAX_SEQS=384

cd /work/llm-discovery || exit 1

# Run the pipeline
bash scripts/process_corpus.sh

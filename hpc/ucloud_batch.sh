#!/usr/bin/env bash
# UCloud Terminal app batch script
# Run inside container with 2x H100 GPU access

# Set vLLM parameters for 2x H100
export VLLM_MODEL="${VLLM_MODEL:-openai/gpt-oss-120b}"
export VLLM_TP=2
export VLLM_GPU_MEM=0.92
export VLLM_MAX_SEQS=128

cd /work/llm-discovery || exit 1

# Run the pipeline
bash scripts/process_corpus.sh

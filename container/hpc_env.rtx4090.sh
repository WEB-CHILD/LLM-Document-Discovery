#!/usr/bin/env bash
# Runtime configuration for local RTX 4090 (single GPU)
# Source: validated during melica spike with google/gemma-4-E4B-it
#
# Sourced by container/entrypoint.sh at container startup.
# Bind-mount the directory containing this file to /data/ when running:
#   apptainer exec --nv --bind ./data:/data pipeline.sif /opt/llm-discovery/container/entrypoint.sh

export VLLM_MODEL="google/gemma-4-E4B-it"
export VLLM_TP=1
export VLLM_GPU_MEM=0.85
export VLLM_MAX_SEQS=128

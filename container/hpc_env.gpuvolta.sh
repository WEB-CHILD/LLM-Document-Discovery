#!/usr/bin/env bash
# Runtime configuration for NCI Gadi gpuvolta queue (4x V100 GPUs)
#
# Sourced by container/entrypoint.sh at container startup.
# Model and TP values sized for 4x V100 32GB GPUs.

export VLLM_MODEL="google/gemma-4-31B-it"
export VLLM_TP=4
export VLLM_GPU_MEM=0.90
export VLLM_MAX_SEQS=64

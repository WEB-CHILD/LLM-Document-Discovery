#!/usr/bin/env bash
# Runtime configuration for NCI Gadi gpuhopper queue (4x H200 GPUs)
#
# Sourced by container/entrypoint.sh at container startup.
# Model and TP values sized for 4x H200 141GB GPUs.

export VLLM_MODEL="openai/gpt-oss-120b"
export VLLM_TP=4
export VLLM_GPU_MEM=0.92
export VLLM_MAX_SEQS=384

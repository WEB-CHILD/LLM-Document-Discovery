#!/usr/bin/env bash
# shellcheck disable=SC2153  # VLLM_* vars are supplied by caller (entrypoint.sh sources hpc_env.sh first)
# Build the `vllm serve` command line from environment variables.
#
# Sourced by container/entrypoint.sh and by tests/test_entrypoint_cmd.py so
# that flag assembly can be verified in isolation without running vLLM.
#
# Required env vars:
#   VLLM_MODEL, VLLM_TP, VLLM_GPU_MEM, VLLM_MAX_SEQS
#
# Optional env vars:
#   VLLM_PORT                 default 8000
#   VLLM_MAX_MODEL_LEN        adds --max-model-len <val>
#   VLLM_DP                   adds --data-parallel-size <val> when >1
#   VLLM_REASONING_PARSER     adds --reasoning-parser <val> (qwen3|gemma4|openai_gptoss|...)
#   VLLM_LANGUAGE_MODEL_ONLY  adds --language-model-only when "1" (frees multimodal KV)
#
# Writes one argument per line to stdout. Callers use `mapfile -t CMD <(build_vllm_cmd)`.

build_vllm_cmd() {
    local port="${VLLM_PORT:-8000}"
    local cmd=(
        vllm serve "$VLLM_MODEL"
        --tensor-parallel-size "$VLLM_TP"
        --gpu-memory-utilization "$VLLM_GPU_MEM"
        --max-num-seqs "$VLLM_MAX_SEQS"
        --port "$port"
        --trust-remote-code
    )

    if [ -n "${VLLM_MAX_MODEL_LEN:-}" ]; then
        cmd+=(--max-model-len "$VLLM_MAX_MODEL_LEN")
    fi

    if [ -n "${VLLM_DP:-}" ] && [ "$VLLM_DP" -gt 1 ] 2>/dev/null; then
        cmd+=(--data-parallel-size "$VLLM_DP")
    fi

    if [ -n "${VLLM_REASONING_PARSER:-}" ]; then
        cmd+=(--reasoning-parser "$VLLM_REASONING_PARSER")
    fi

    if [ "${VLLM_LANGUAGE_MODEL_ONLY:-0}" = "1" ]; then
        cmd+=(--language-model-only)
    fi

    printf '%s\n' "${cmd[@]}"
}

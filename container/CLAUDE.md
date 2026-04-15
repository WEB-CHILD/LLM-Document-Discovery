# container/

Apptainer/Singularity container definition and runtime configuration for the LLM Discovery pipeline.

Freshness: 2026-04-15

## Purpose

Package vLLM + llm-discovery into a single container image for reproducible GPU execution on both local machines (Apptainer) and HPC (Singularity on Gadi).

## Contracts

### pipeline.def

Built on `vllm/vllm-openai:v0.19.0`. Installs `transformers>=5.5.0` and `llm-discovery` package via `uv pip install --system`. Bakes tiktoken vocab files (`o200k_base`, `cl100k_base`) with verified SHA256 checksums for offline HPC use.

Environment variables set at build time: `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `PYTHONUNBUFFERED=1`, `TIKTOKEN_ENCODINGS_BASE=/opt/tiktoken`.

Only `src/`, `pyproject.toml`, `README.md`, and `container/entrypoint.sh` are copied into the image. Runtime data is bind-mounted.

### entrypoint.sh

Orchestrates vLLM server + pipeline execution inside the container.

Required bind mounts:
- `<data-dir>:/data` -- must contain: `hpc_env.sh`, `corpus.db`, `system_prompt.txt`, `prompts/`, `out/`
- `<hf-cache>:/model_cache` with `--env HF_HOME=/model_cache`

Required env vars (from `/data/hpc_env.sh`): `VLLM_MODEL`, `VLLM_TP`, `VLLM_GPU_MEM`, `VLLM_MAX_SEQS`.
Optional: `VLLM_PORT` (default 8000), `VLLM_MAX_MODEL_LEN`, `VLLM_DP`.

Invariants:
- No `set -e` -- EXIT trap must always fire to kill vLLM background process
- `cd /data` before running pipeline so relative paths resolve correctly
- Health check: polls `localhost:{VLLM_PORT}/health` every 5s, 3600s timeout
- Only runs GPU stages (process + import-results); prep-db and preflight run on host

### hpc_env.*.sh

Per-GPU environment configs. Not copied into container -- bind-mounted as `/data/hpc_env.sh` at runtime. Generated dynamically by `platform.generate_hpc_env()` for deploy/init workflows. Static files here are reference configs for manual/E2E testing.

| File | GPU | Model |
|------|-----|-------|
| `hpc_env.rtx4090.sh` | RTX 4090 | google/gemma-4-E4B-it |
| `hpc_env.gpuvolta.sh` | V100 x4 | google/gemma-4-31B-it |
| `hpc_env.gpuhopper.sh` | H200 x4 | openai/gpt-oss-120b (unverified) |

## Dependencies

- Parent: `src/llm_discovery/` (installed inside container)
- Consumed by: `src/llm_discovery/local_runner.py`, `hpc/gadi.pbs.template`
- Build requires: Apptainer with root/fakeroot privileges

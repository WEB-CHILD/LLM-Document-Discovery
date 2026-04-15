# LLM Document Discovery

Reproducible pipeline for classifying historical web documents (1996-2005) using LLMs on GPU hardware (local RTX 4090 or NCI Gadi HPC).

Freshness: 2026-04-15

## Purpose

Fetch archived web pages from the Internet Archive, classify them against 21 category prompts using vLLM-served models, and produce a structured SQLite database of classifications with blockquote evidence.

## Architecture

### Execution Model

Two execution paths, selected by `submission` field in `config/platforms.yaml`:

| Submission | Platforms | How it runs |
|------------|-----------|-------------|
| `apptainer` | `local-e4b`, `local-oss20b` | Host-side prep (prep-db, preflight), then Apptainer container runs vLLM + process + import-results |
| `pbs` | `gadi` | Rsync code/data/container to HPC, submit PBS job that runs Singularity container |

The container (`container/pipeline.def`) is built on vLLM's Docker image and contains the full `llm-discovery` package. Runtime data (corpus.db, prompts, system_prompt.txt) is bind-mounted at `/data/`. Model weights are bind-mounted at `/model_cache/`.

### Pipeline Stages

1. **fetch** -- Download pages from Internet Archive Wayback Machine via `id_` endpoint
2. **prep-db** -- Create SQLite database, sync 21 category prompts from `prompts/*.yaml`, sync documents with SHA-256 change detection
3. **preflight** -- Validate documents contain usable text
4. **process** -- Streaming concurrent requests to vLLM server (reader thread, bounded work queue, ThreadPoolExecutor)
5. **import-results** -- Read JSON result files into database with `INSERT OR IGNORE` idempotency

Stages 1-3 run on the host. Stages 4-5 run inside the container (orchestrated by `container/entrypoint.sh`).

### Container Entrypoint Contract

`container/entrypoint.sh` expects:
- Bind mount: `<data-dir>:/data` containing `hpc_env.sh`, `corpus.db`, `system_prompt.txt`, `prompts/`, `out/`
- Bind mount: `<hf-cache>:/model_cache` with `HF_HOME=/model_cache`
- `hpc_env.sh` must export: `VLLM_MODEL`, `VLLM_TP`, `VLLM_GPU_MEM`, `VLLM_MAX_SEQS`
- Optional: `VLLM_PORT` (default 8000), `VLLM_MAX_MODEL_LEN`, `VLLM_DP`
- EXIT trap always fires to kill the vLLM background process

## Contracts

### CLI Commands (src/llm_discovery/cli.py)

Entry point: `llm-discovery` (Typer app).

| Command | Key Options | Contract |
|---------|-------------|----------|
| `build` | `--output`, `--validate` | Calls `apptainer build`, validates .sif (>1GB, CLI callable inside) |
| `download-model` | `--gpu-queue` | Downloads model weights to local HF cache, checks disk space |
| `init` | `--platform`, `--project`, `--gpu-queue`, `--container-image` | First-time HPC setup: stage container, upload env, upload model cache, submit ping job. Call order: stage -> env -> model -> ping |
| `fetch` | | Download pages from Internet Archive |
| `prep-db` | `--db`, `--input-dir`, `--prompts-dir` | Create/populate corpus database |
| `preflight` | `--db` | Validate documents in corpus database |
| `validate` | `--platform`, `--project` | Check remote HPC environment readiness |
| `deploy` | `--platform`, `--project`, `--gpu-queue`, `--container-image`, `--data-dir` | Assemble data dir (prep-db, preflight, assets), rsync, stage container, upload data, submit job |
| `status` | `--platform`, `--job-id`, `--project`, `--watch` | Check job status; `--watch` polls every 30s, fetches output on completion |
| `retrieve` | `--platform`, `--project` | Pull corpus.db back from HPC |
| `run` | `--platform`, `--gpu-queue`, `--yes` | End-to-end pipeline; routes to `_run_container_pipeline` for `apptainer` submission or `_run_remote_pipeline` for PBS |
| `process` | `--db`, `--output-dir`, `--server-url`, `--model` | Run LLM classification |
| `import-results` | `--db`, `--input-dir` | Import JSON results into database |

### Platform Configuration (src/llm_discovery/platform.py)

`PlatformConfig` model fields: `display_name`, `ssh_host`, `remote_base`, `gpu_type`, `gpu_queue`, `submission`, `container_image`, `modules`, `checks`.

GPU queue configs are in `_GPU_QUEUE_CONFIGS` dict. Known queues: `gpuhopper`, `gpuvolta`, `gpuvolta-e4b`, `gpuhopper-oss20b`, `RTX4090-e4b`, `RTX4090-oss20b`. Each maps to a model, TP size, GPU memory utilization, and max sequences.

Key platform functions:
- `stage_container_image(platform, project, local_sif) -> str` -- rsync .sif to `/scratch/{project}/containers/`, verify SHA256 post-transfer
- `generate_hpc_env(gpu_queue) -> str` -- generate shell script exporting vLLM env vars for a queue
- `upload_model_cache(platform, project, gpu_queue)` -- rsync model weights from local HF cache to remote
- `upload_data_dir(platform, project, data_dir)` -- rsync data dir (corpus.db, prompts, system_prompt.txt) to remote, excludes hpc_env.sh
- `submit_ping_job(platform, project, gpu_queue, container_path) -> str` -- submit smoke test PBS job
- `submit_gadi_job(platform, project, gpu_queue, container_path) -> str` -- submit production PBS job
- `fetch_remote_file(platform, remote_path) -> str | None` -- cat a file via SSH
- `resolve_pbs_queue(gpu_queue) -> str` -- strip suffixes like `-e4b`, `-oss20b` to get PBS routing queue

### Local Container Runner (src/llm_discovery/local_runner.py)

- `check_container_freshness(sif_path) -> bool` -- True if .sif is newer than all files in `src/` and `container/`
- `run_container_pipeline(data_dir, sif_path, input_dir, gpu_queue)` -- host-side prep then `apptainer exec --nv` with bind mounts

### PBS Template (hpc/gadi.pbs.template)

Placeholders: `{{GPU_QUEUE}}`, `{{NCI_PROJECT}}`, `{{CONTAINER_PATH}}`. Runs `singularity exec --nv` (Gadi uses Singularity, not Apptainer). Binds `/data` and `/model_cache`. Sources `hpc_env.sh` inside container for vLLM config. Redirects vLLM compile cache and torch inductor cache to `$PBS_JOBFS`.

## Dependencies

See `docs/dependency-rationale.md` for falsifiable justifications.

Runtime: typer, rich, warcio, markdownify, requests, pydantic, pyyaml, langchain-text-splitters, fabric.
GPU optional: vllm.
Dev: pytest, pre-commit, ruff, shellcheck-py, ty, complexipy.

## Invariants

- Container entrypoint EXIT trap must always fire (no `set -e`) to kill vLLM background process
- `.sif` files and `container/` directory are excluded from rsync to remote (staged separately with SHA256 verification)
- `hpc_env.sh` is excluded from data dir rsync (uploaded separately by `upload_hpc_env`)
- PBS template uses `singularity` (not `apptainer`) because Gadi provides Singularity
- `_GPU_QUEUE_CONFIGS` is the single source of truth for model/GPU parameter mappings
- Container runs as calling user (not root) -- do not bind to `/root/.cache/huggingface`
- Tiktoken vocab files are baked into the container at build time for offline HPC use
- Tests marked `container` require pre-built `pipeline.sif`; tests marked `gpu` require NVIDIA GPU
- Default pytest excludes: `not network and not gpu and not container`

## Directory Structure

```
config/           Platform and machine YAML configs
container/        Apptainer definition, entrypoint, per-GPU env configs
hpc/              PBS job templates
prompts/          YAML category definitions (21 categories)
scripts/          Legacy shell orchestration (being replaced by container entrypoint)
src/llm_discovery/  Python package
tests/            pytest suite
```

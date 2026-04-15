# Container CLI Verbs Design

**GitHub Issue:** None

## Summary

This document specifies three new or enhanced CLI verbs for the `llm-discovery` tool: `build`, `init`, and an updated `deploy`. Together they form a complete, linear workflow for running the document-discovery pipeline on a remote HPC cluster (Gadi at NCI) using a containerised environment. The container bundles the pipeline code, Python dependencies, and the vLLM inference server into a single Apptainer `.sif` image, eliminating the glibc version mismatch that prevents vLLM from running directly on Gadi's host OS.

The approach follows a strict separation of concerns: `build` runs locally under `sudo` and produces the container image; `init` handles first-time HPC setup by staging the image, rsyncing locally-cached model weights, and submitting a smoke test job; `deploy` transfers corpus data and submits the main pipeline job. Each verb is independently re-runnable and maps to a distinct privilege context (local sudo, remote SSH, PBS job scheduler). The CLI is implemented with Typer and orchestrates calls to platform functions in `platform.py` using Fabric for SSH and rsync for file transfer, following patterns already established in the codebase.

## Definition of Done

The `llm-discovery` CLI provides a complete, linear verb chain for container-based HPC processing with no manual SSH steps:

- **`build`**: Explains why sudo is needed, runs `sudo apptainer build` via subprocess, then validates the resulting `.sif` (exists, >1GB, CLI callable inside container). Single invocation: build then validate.
- **`init`**: Stages `.sif` to remote HPC, rsyncs locally-cached model weights to remote (from `$HF_HUB_CACHE` or `$HF_HOME/hub` or `~/.cache/huggingface/hub`), submits a minimal smoke test PBS job (vLLM starts, responds to "PING?", exits). User checks smoke test result with `status`.
- **`deploy` enhanced**: In addition to current staging + job submission, uploads corpus data (corpus.db, system_prompt.txt, prompts/) to the remote data directory.
- **README updated**: Documents the clean verb chain: `build → init → fetch → prep-db → preflight → deploy → status → retrieve`.

## Acceptance Criteria

### container-cli-verbs.AC1: build command
- **container-cli-verbs.AC1.1 Success:** `build` runs `sudo apptainer build` via subprocess, produces `.sif`
- **container-cli-verbs.AC1.2 Success:** `build` prints explanation of why sudo is needed before exec
- **container-cli-verbs.AC1.3 Success:** `build --validate` confirms `.sif` exists, >1GB, CLI callable inside container
- **container-cli-verbs.AC1.4 Failure:** `build --validate` exits non-zero with clear error if `.sif` missing or invalid

### container-cli-verbs.AC2: init command
- **container-cli-verbs.AC2.1 Success:** `init` stages `.sif` to `/scratch/{project}/containers/`
- **container-cli-verbs.AC2.2 Success:** `init` rsyncs locally-cached model weights to remote HF cache
- **container-cli-verbs.AC2.3 Success:** `init` submits ping job and returns job ID
- **container-cli-verbs.AC2.4 Failure:** `init` fails with clear error if model weights not found in local HF cache
- **container-cli-verbs.AC2.5 Failure:** `init` fails with clear error if local `.sif` doesn't exist

### container-cli-verbs.AC3: deploy data upload
- **container-cli-verbs.AC3.1 Success:** `deploy --data-dir` rsyncs corpus.db, system_prompt.txt, prompts/ to remote
- **container-cli-verbs.AC3.2 Failure:** `deploy` fails with clear error if `--data-dir` missing required files
- **container-cli-verbs.AC3.3 Success:** `deploy` does not overwrite remote `hpc_env.sh` with local copy from data dir

### container-cli-verbs.AC4: README documentation
- **container-cli-verbs.AC4.1 Success:** README documents complete verb chain with `<project-code>` placeholders
- **container-cli-verbs.AC4.2 Success:** README separates first-time setup from per-corpus steps

## Glossary

- **Apptainer**: An HPC-oriented container runtime (formerly Singularity) that runs container images as unprivileged processes on cluster nodes. Used here to package the full pipeline environment as a `.sif` file.
- **`.sif` (Singularity Image Format)**: The single-file, read-only container image produced by `apptainer build`. Portable across HPC systems.
- **Gadi**: The National Computational Infrastructure (NCI) supercomputer in Australia. The target HPC platform for this pipeline.
- **PBS (Portable Batch System)**: The job scheduler used on Gadi. Jobs are submitted with `qsub` and monitored with `qstat`.
- **vLLM**: An inference server for large language models. Exposes an OpenAI-compatible HTTP API. The pipeline runs it inside the container on a GPU node to classify documents.
- **HF_HUB_CACHE / HF_HOME**: Environment variables controlling the local HuggingFace cache location. `HF_HUB_CACHE` overrides the `hub/` subdirectory path; `HF_HOME` sets the base directory (default `~/.cache/huggingface`). Model weights live at `<cache>/hub/models--<org>--<name>/`.
- **Fabric**: A Python library for SSH automation. Used in `platform.py` for remote commands (`conn.run()`) and file uploads (`conn.put()`).
- **Typer**: A Python CLI framework. Supports reading option values from environment variables via the `envvar` parameter.
- **ping job / smoke test**: A minimal PBS job (1 GPU, 30 minutes) submitted by `init` to verify the container starts correctly and vLLM responds before real work is attempted.
- **`hpc_env.sh`**: A generated shell script encoding GPU-specific configuration (model, tensor parallelism, memory). Managed separately from corpus data.
- **corpus.db**: A SQLite database containing the document corpus to be processed. Required in `--data-dir` for `deploy`.
- **`pipeline.def`**: The Apptainer definition file specifying how to build the container image.
- **verb chain**: The ordered sequence of CLI commands (`build → init → fetch → prep-db → preflight → deploy → status → retrieve`) constituting the complete end-to-end workflow.
- **`_ensure_validated()`**: An existing guard function confirming platform configuration is complete before remote operations.

## Architecture

Three new/modified CLI commands compose platform functions from `src/llm_discovery/platform.py`, following the existing pattern where CLI commands (`cli.py`) validate inputs and orchestrate calls to platform functions.

### `build` command

Local-only. No platform functions needed.

1. Validates `container/pipeline.def` exists
2. Prints explanation of why sudo is required
3. Runs `subprocess.run(["sudo", "apptainer", "build", output, "container/pipeline.def"])` — keeps the Python process alive so validation runs automatically after build
4. Validates the resulting `.sif`: exists, size >1GB, `apptainer exec <sif> llm-discovery --help` returns 0
5. When invoked with `--validate`, skips build (steps 2-3) and runs only validation (step 4)

Options: `--output` (default: `pipeline.sif`), `--validate` (validate only, skip build).

`build && init` works because subprocess preserves the Python process and propagates non-zero exit codes.

### `init` command

First-time HPC environment setup. Composes existing and new platform functions:

1. `_ensure_validated()` — validate platform config
2. Validate local `.sif` exists
3. `stage_container_image()` — rsync `.sif` to `/scratch/{project}/containers/` (existing)
4. `upload_hpc_env()` — generate and upload `hpc_env.sh` (existing)
5. `upload_model_cache()` — **new**. Resolves local HF cache directory from `$HF_HUB_CACHE`, or `$HF_HOME/hub`, or `~/.cache/huggingface/hub` (in that order). Looks up model name from `generate_hpc_env()` config for the selected queue (e.g. `google/gemma-4-E4B-it` → `models--google--gemma-4-E4B-it`). Validates the model directory exists locally. Rsyncs it to `/scratch/{project}/hf_cache/hub/` on remote.
6. `submit_ping_job()` — **new**. Reads `hpc/gadi.ping.template`, substitutes `{{GPU_QUEUE}}`, `{{NCI_PROJECT}}`, `{{CONTAINER_PATH}}` placeholders, uploads via `conn.put()`, submits with `qsub`. Returns job ID.
7. Prints job ID and `status` command for user to check result.

Options: `--platform`, `--project`, `--gpu-queue`, `--container-image` (default: `pipeline.sif`).

### `deploy` command (enhanced)

Adds `--data-dir` option. After staging `.sif` and uploading `hpc_env.sh`, rsyncs the data directory to `/scratch/{project}/llm-discovery/data/` on remote.

1-4. Existing flow (validate, rsync code, stage `.sif`, upload `hpc_env.sh`)
5. `upload_data_dir()` — **new**. Validates required files (corpus.db, system_prompt.txt, prompts/) exist in `--data-dir`. Rsyncs to remote `/data/`, excluding `hpc_env.sh` (managed by step 4).
6. `submit_gadi_job()` — existing.

`--data-dir` is required for Gadi deploys.

### Data flow

```
Local machine                         Gadi
─────────────                         ────
build:
  pipeline.def ──apptainer build──> pipeline.sif

init:
  pipeline.sif ──rsync──────────> /scratch/{project}/containers/pipeline.sif
  ~/.cache/huggingface/hub/models--* ──rsync──> /scratch/{project}/hf_cache/hub/models--*
                ──qsub ping job──> vLLM starts, responds to PING?, exits

deploy:
  data/ ────────rsync────────────> /scratch/{project}/llm-discovery/data/
                                    ├── corpus.db
                                    ├── system_prompt.txt
                                    ├── prompts/
                                    └── hpc_env.sh (generated)
                ──qsub pipeline──> singularity exec ... entrypoint.sh
```

## Decision Record

### DR1: Separate `build` and `init` rather than single `setup` command
**Status:** Accepted
**Confidence:** High
**Reevaluation triggers:** If build and init are always run together in practice.

**Decision:** We chose separate `build` (local, sudo) and `init` (remote, SSH) commands rather than a single `setup` that does both.

**Consequences:**
- **Enables:** Building locally without HPC access. Rebuilding without re-initialising. Clear separation of local vs remote operations.
- **Prevents:** One-command setup. User must run two commands for first-time setup.

**Alternatives considered:**
- **Single `setup` command:** Rejected because sudo and SSH are fundamentally different privilege contexts. Combining them creates confusing error modes.

### DR2: Separate ping template rather than mode in pipeline template
**Status:** Accepted
**Confidence:** High
**Reevaluation triggers:** If template divergence causes maintenance burden.

**Decision:** We chose a dedicated `hpc/gadi.ping.template` for the smoke test rather than adding a `{{MODE}}` switch to the existing pipeline template.

**Consequences:**
- **Enables:** Minimal resource request (1 GPU, 30min) for smoke test. Clear intent when reading templates. Independent evolution.
- **Prevents:** Reusing PBS resource settings between templates.

**Alternatives considered:**
- **Mode flag in existing template:** Rejected because the resource requirements (1 GPU vs 4, 30min vs 4h) differ too much for clean conditionals.

### DR3: Explicit `--data-dir` rather than assembling from conventions
**Status:** Accepted
**Confidence:** High
**Reevaluation triggers:** If users consistently prepare data in the same conventional location.

**Decision:** We chose an explicit `--data-dir` option for deploy rather than having deploy find corpus.db, system_prompt.txt, and prompts/ from their conventional repo locations.

**Consequences:**
- **Enables:** Clear, auditable data flow. User controls exactly what gets deployed. Works with prepare_container_data.sh output directly.
- **Prevents:** Zero-argument deploy for repeat runs.

**Alternatives considered:**
- **Convention-based assembly:** Rejected because it creates implicit coupling between repo layout and deploy behaviour. Explicit is better.

## Existing Patterns

Investigation found these patterns in the current codebase:

- **CLI structure:** `@app.command()` decorators in `cli.py`, `typer.Option()` for parameters, `_ensure_validated()` guard before deploy operations. New commands follow this pattern.
- **Platform composition:** `deploy()` in `cli.py` orchestrates `rsync_to_remote()` → `stage_container_image()` → `upload_hpc_env()` → `submit_gadi_job()` from `platform.py`. `init` follows the same composition pattern.
- **SSH via Fabric:** `Connection(platform.ssh_host)` with context manager, `conn.run()` for commands, `conn.put()` for file upload. All new platform functions follow this.
- **PBS template substitution:** `{{PLACEHOLDER}}` replacement in `submit_gadi_job()`. `submit_ping_job()` follows the same pattern with a separate template.
- **rsync for file transfer:** `subprocess.run(["rsync", "-avz", ...], check=True)`. `upload_data_dir()` follows this pattern.

No divergence from existing patterns. All new code follows established conventions.

<!-- START_PHASE_1 -->
### Phase 1: `build` command
**Goal:** Local container build with sudo explanation and validation.

**Components:**
- `build` command in `src/llm_discovery/cli.py` — validates def file exists, runs sudo apptainer build via subprocess, then validates .sif. `--validate` skips build and runs validation only.
- No new platform functions (local-only operation)

**Dependencies:** None (first phase). Requires `container/pipeline.def` from apptainer-pipeline branch.

**Done when:** `llm-discovery build` explains sudo and builds a `.sif`. `llm-discovery build --validate` confirms the `.sif` is valid (exists, >1GB, CLI callable inside). Tests verify both paths.
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: `upload_model_cache()` and `submit_ping_job()` platform functions
**Goal:** New platform functions for init workflow, with tests.

**Components:**
- `upload_model_cache()` in `src/llm_discovery/platform.py` — resolves local HF cache path (`$HF_HUB_CACHE` / `$HF_HOME/hub` / `~/.cache/huggingface/hub`), validates model directory exists, rsyncs to remote `/scratch/{project}/hf_cache/hub/`
- `submit_ping_job()` in `src/llm_discovery/platform.py` — reads `gadi.ping.template`, substitutes placeholders, uploads and submits via qsub
- `hpc/gadi.ping.template` — short PBS job (1 GPU, 30min) that starts vLLM, curls /v1/completions with "PING?", prints response, exits
- Tests in `tests/test_platform.py` — mock subprocess for rsync, mock SSH for ping job submission

**Dependencies:** Phase 1

**Done when:** `upload_model_cache()` rsyncs the correct model directory to remote. `submit_ping_job()` substitutes template and submits. All tests pass with mocked SSH/subprocess.
<!-- END_PHASE_2 -->

<!-- START_PHASE_3 -->
### Phase 3: `init` CLI command
**Goal:** Wire init command to platform functions.

**Components:**
- `init` command in `src/llm_discovery/cli.py` — validates inputs, calls stage_container_image → upload_hpc_env → upload_model_cache → submit_ping_job

**Dependencies:** Phase 2

**Done when:** `llm-discovery init --platform gadi --project <code> --gpu-queue gpuvolta` stages container, uploads cached weights, and submits ping job. Tests verify CLI wiring with mocked platform functions.
<!-- END_PHASE_3 -->

<!-- START_PHASE_4 -->
### Phase 4: `upload_data_dir()` and deploy enhancement
**Goal:** Deploy uploads corpus data before job submission.

**Components:**
- `upload_data_dir()` in `src/llm_discovery/platform.py` — validates required files in local data dir, rsyncs to remote `/data/`, excludes `hpc_env.sh`
- `deploy` command update in `src/llm_discovery/cli.py` — adds `--data-dir` option (required for Gadi), calls `upload_data_dir()` between hpc_env upload and job submission
- Tests in `tests/test_platform.py` — mock rsync, verify required file validation and exclude pattern

**Dependencies:** Phase 3

**Done when:** `llm-discovery deploy --data-dir ./data ...` uploads data directory contents to remote. Missing required files produce clear error. Tests pass.
<!-- END_PHASE_4 -->

<!-- START_PHASE_5 -->
### Phase 5: Gadi UAT
**Goal:** End-to-end verification on real Gadi hardware.

**Components:**
- Run `build` locally, verify `.sif` produced
- Run `init` against Gadi, verify model weights downloaded and ping job responds
- Run full verb chain: `fetch → prep-db → preflight → deploy → status → retrieve`
- Verify results in corpus.db
- Update README with verified verb chain documentation (using `<project-code>` placeholders)

**Dependencies:** Phase 4

**Done when:** Complete verb chain produces analysed corpus on Gadi with no manual SSH steps. README documents the flow.
<!-- END_PHASE_5 -->

## Additional Considerations

**Model weights:** `init` rsyncs locally-cached weights to remote. The user must have the model cached locally (from running the pipeline locally or via `huggingface-cli download`). Gated model access (Gemma 4) requires prior acceptance of the model's licence on huggingface.co and a valid `$HF_TOKEN` during the local download — but the token is never sent to the remote.

**Idempotency:** All commands are safe to re-run. `build` overwrites existing `.sif`. `init` re-stages and re-rsyncs (rsync is incremental). `deploy` re-uploads data and submits a new job.

**Platform extensibility:** Only Gadi is supported for `init` and container-based `deploy`. UCloud path is unchanged (manual submission). Adding a new platform would require new template files and platform function implementations.

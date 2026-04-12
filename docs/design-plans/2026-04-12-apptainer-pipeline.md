# Apptainer Pipeline Container Design

**GitHub Issue:** None

## Summary

This project packages the LLM document discovery pipeline into a portable Apptainer container image so that the same artifact runs identically on a local RTX 4090 development machine and on the NCI Gadi HPC cluster. The root problem being solved is a glibc version incompatibility on Gadi that prevents installing vLLM directly into a remote Python virtual environment — the container carries its own glibc, CUDA, PyTorch, and vLLM stack, eliminating that constraint entirely.

The approach layers the project's own Python package (`llm-discovery`) on top of the pre-built `vllm/vllm-openai` Docker image, converted to a single immutable `.sif` file via `apptainer build`. At runtime the container is stateless: a small shell script sourced from a bind-mounted data directory configures which model and GPU layout to use, then the entrypoint launches vLLM as a background process, polls its health endpoint, invokes the `llm-discovery process` and `import-results` CLI commands against a pre-built corpus database, and exits cleanly. Deployment to Gadi is handled by the existing deploy automation, which will `scp` the `.sif` file to scratch storage and submit a PBS job that invokes the container with `singularity exec --nv`.

## Definition of Done

1. An Apptainer `.sif` image (definition file in repo) containing vLLM + llm-discovery + all Python dependencies
2. Local end-to-end test: container processes demo corpus on RTX 4090 with Gemma 4 E4B — pre-built corpus.db in, vLLM starts, `llm-discovery process` runs, `llm-discovery import-results` runs, results written to mounted output directory, clean exit
3. Gadi integration: deploy automation stages the `.sif` to `/scratch/as07/`, PBS template launches via `singularity exec --nv`, replacing the broken `build_remote_venv()` path
4. Final UAT: job submitted on Gadi, corpus processed, results retrieved successfully

## Acceptance Criteria

### apptainer-pipeline.AC1: Buildable container image
- **apptainer-pipeline.AC1.1 Success:** `apptainer build` produces a `.sif` from `container/pipeline.def`
- **apptainer-pipeline.AC1.2 Success:** llm-discovery CLI is callable inside the container (`apptainer exec pipeline.sif llm-discovery --help`)
- **apptainer-pipeline.AC1.3 Failure:** Build fails with clear error if `vllm/vllm-openai` base image is unavailable

### apptainer-pipeline.AC2: Local end-to-end processing
- **apptainer-pipeline.AC2.1 Success:** Container processes all documents in corpus.db and writes JSON results to mounted `out/` directory
- **apptainer-pipeline.AC2.2 Success:** `import-results` populates corpus.db result tables, readable from host after container exits
- **apptainer-pipeline.AC2.3 Success:** Container exits 0 after successful run, vLLM process is not left running
- **apptainer-pipeline.AC2.4 Failure:** Container exits non-zero and kills vLLM if `process` command fails mid-run (EXIT trap fires)
- **apptainer-pipeline.AC2.5 Failure:** Container exits non-zero with clear message if required env vars (VLLM_MODEL, VLLM_TP, VLLM_GPU_MEM, VLLM_MAX_SEQS) are missing from hpc_env.sh

### apptainer-pipeline.AC3: Deploy automation integration
- **apptainer-pipeline.AC3.1 Success:** `deploy` command scp's `.sif` to `/scratch/as07/containers/` on Gadi
- **apptainer-pipeline.AC3.2 Success:** PBS job template invokes `singularity exec --nv` with correct bind mounts
- **apptainer-pipeline.AC3.3 Failure:** `deploy` fails with clear error if `.sif` file doesn't exist locally
- **apptainer-pipeline.AC3.4 Failure:** `deploy` fails with clear error if sha256 checksum of remote `.sif` doesn't match local after scp

### apptainer-pipeline.AC4: Gadi UAT
- **apptainer-pipeline.AC4.1 Success:** PBS job completes on gpuvolta queue, results retrievable to local machine
- **apptainer-pipeline.AC4.2 Failure:** Job fails gracefully if model weights not pre-downloaded (`HF_HUB_OFFLINE=1` prevents hang)

## Glossary

- **Apptainer**: A container runtime designed for HPC systems, formerly known as Singularity. Unlike Docker, it does not require a root daemon and is the supported container technology on Gadi. `.sif` files are its portable image format.
- **SIF (`.sif`)**: Singularity Image Format — a single read-only file containing the entire container filesystem. Copied and executed directly without unpacking.
- **vLLM**: An open-source Python library that serves large language models over an OpenAI-compatible HTTP API. Handles GPU memory management, batching, and tensor parallelism.
- **`vllm/vllm-openai`**: The official Docker image published by the vLLM project. Ships a working combination of CUDA, PyTorch, and vLLM, used here as the base layer for the Apptainer image.
- **Gemma 4 E4B**: Google's Gemma 4 model at the effective 4-billion-parameter variant. Fits a single 24GB GPU at BF16.
- **corpus.db**: A SQLite database containing the documents to be processed. Produced by the `prep-db` pipeline stage on the host before the container is invoked.
- **`hpc_env.sh`**: A shell script bind-mounted into the container at `/data/hpc_env.sh`. Sets environment variables controlling model selection, GPU memory fraction, tensor parallelism degree, and other vLLM parameters.
- **PBS (Portable Batch System)**: The job scheduler used on Gadi. Jobs are submitted via `qsub` with `#PBS` directives.
- **Gadi**: NCI Australia's primary supercomputer. Uses `gpuvolta` (V100 GPUs) and `gpuhopper` (H200 GPUs) queues.
- **Tensor parallelism (TP)**: Distributing a single model across multiple GPUs by splitting weight tensors. Controlled by `VLLM_TP`; relevant for multi-GPU nodes on Gadi.
- **`HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE`**: Environment variables that prevent Hugging Face libraries from attempting network calls. Set to `1` inside the container so compute nodes without internet don't hang.
- **Bind mount**: A mechanism (`--bind src:dest`) making a host directory available inside the container. Used to supply corpus database, model weights, and output directory without baking them into the image.
- **EXIT trap**: A Bash feature (`trap cleanup EXIT`) that runs a cleanup function whenever the shell exits, regardless of reason. Used to ensure vLLM is always killed.

## Architecture

Single Apptainer `.sif` image built from `vllm/vllm-openai:v0.19.0` (pin updated when new stable releases are verified). The image contains vLLM, CUDA, PyTorch, and the llm-discovery project with all Python dependencies. Model weights and corpus data are bind-mounted at runtime.

**Baked into the image (immutable):**
- vLLM + CUDA + PyTorch (from `vllm/vllm-openai` base via `Bootstrap: docker`)
- llm-discovery project source copied into image via `%files`, installed via `pip install` in `%post`
- `transformers>=5.5.0` (Gemma 4 requirement)
- `container/entrypoint.sh` orchestration script
- `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` as default environment

**Mounted at runtime (varies per run):**
- `/data/` — corpus.db, system_prompt.txt, hpc_env.sh
- `/data/out/` — JSON results output, vLLM logs
- HuggingFace model cache — bind-mounted from host filesystem

**Entrypoint flow:**
1. Source `/data/hpc_env.sh` (sets VLLM_MODEL, VLLM_TP, VLLM_GPU_MEM, VLLM_MAX_SEQS, optional VLLM_PORT and VLLM_MAX_MODEL_LEN)
2. Validate required env vars are set (VLLM_MODEL, VLLM_TP, VLLM_GPU_MEM, VLLM_MAX_SEQS) — fail fast with clear message if missing
3. Launch `vllm serve` as background process, log to `/data/out/vllm.log`
4. Poll `http://localhost:$VLLM_PORT/health` (3600s timeout, 5s intervals)
5. Run `llm-discovery process --server-url http://localhost:$VLLM_PORT --db-path /data/corpus.db --output-dir /data/out/`
6. Run `llm-discovery import-results --db-path /data/corpus.db --results-dir /data/out/`
7. Kill vLLM background process
8. Exit with appropriate exit code

EXIT trap ensures vLLM is killed on any failure. No tmux — background process management only.

The container is stateless: same `.sif` + different `hpc_env.sh` = different model/GPU configuration. One image serves RTX 4090 (local), V100 (Gadi gpuvolta), H200 (Gadi gpuhopper).

**Local run command:**
```
apptainer exec --nv \
  --bind ./data:/data \
  --bind ~/.cache/huggingface:/root/.cache/huggingface \
  pipeline.sif /opt/llm-discovery/container/entrypoint.sh
```

**Gadi run command (inside PBS script):**
```
module load singularity
singularity exec --nv \
  --bind /scratch/as07/$NCI_PROJECT:/data \
  --bind $HF_CACHE_DIR:/root/.cache/huggingface \
  $CONTAINER_PATH /opt/llm-discovery/container/entrypoint.sh
```

Gadi auto-mounts `/scratch`, `/jobfs`, home directories, and NVIDIA driver libraries into Singularity containers.

## Decision Record

### DR1: Apptainer/Singularity everywhere instead of Docker
**Status:** Accepted
**Confidence:** High
**Reevaluation triggers:** If Apptainer PPA breaks on Ubuntu 24.04; if Gadi changes container runtime.

**Decision:** We chose Apptainer natively on the development machine instead of Docker with a Docker-to-Singularity conversion step.

**Consequences:**
- **Enables:** Identical container runtime locally and on Gadi. Same `.sif` image, same `--nv` flag, same bind-mount semantics. Zero translation layer.
- **Prevents:** Using Docker-specific features (layer caching during dev, `--gpus` device isolation). Requires `sudo` for `apptainer build`.

**Alternatives considered:**
- **Docker locally + convert to Singularity for Gadi:** Rejected because it introduces a conversion step and a class of "works in Docker but not in Singularity" bugs.
- **Docker locally + Docker on Gadi:** Not an option — Gadi only provides Singularity.

### DR2: vllm/vllm-openai as base image rather than nvidia/cuda + manual install
**Status:** Accepted
**Confidence:** High
**Reevaluation triggers:** If vLLM stable drops Gemma 4 support; if image size becomes a transfer bottleneck to Gadi; if we need a Python version not in the vLLM image.

**Decision:** We chose the pre-built vllm/vllm-openai image as the Apptainer base layer, installing only the llm-discovery project on top.

**Consequences:**
- **Enables:** Eliminates CUDA/PyTorch/vLLM compatibility management. vLLM team maintains the working combination.
- **Prevents:** Control over Python version, CUDA version, or image size optimisation. Image is ~13GB.

**Alternatives considered:**
- **nvidia/cuda:12.4-runtime + pip install vLLM:** Rejected because managing the CUDA/PyTorch/vLLM compatibility matrix manually is fragile and the nightly wheel installation is error-prone.

### DR3: Container runs GPU stages only (process + import-results), not full pipeline
**Status:** Accepted
**Confidence:** High
**Reevaluation triggers:** If prep-db or preflight gains GPU dependencies; if separating stages creates data consistency issues.

**Decision:** We chose to run only the GPU-dependent stages (process, import-results) inside the container. prep-db and preflight run on the host or login node before container launch.

**Consequences:**
- **Enables:** Simpler container (no raw corpus files needed, just pre-built corpus.db). Faster iteration on prep stages without rebuilding the container.
- **Prevents:** Fully self-contained "data in, results out" workflow from raw input. Requires a two-step process: host prep then container run.

**Alternatives considered:**
- **Full pipeline in container:** Rejected because prep-db and preflight don't need GPU and adding them increases mount complexity (raw corpus files) without benefit.

### DR4: scp image to Gadi rather than registry pull
**Status:** Accepted
**Confidence:** Medium
**Reevaluation triggers:** If image changes frequently enough that scp becomes a bottleneck; if team grows and needs shared image access.

**Decision:** We chose to scp the `.sif` file directly to `/scratch/as07/` on Gadi rather than publishing to a container registry and pulling on the login node.

**Consequences:**
- **Enables:** Simple deployment with no registry infrastructure. Works immediately.
- **Prevents:** Version management, shared access, and CI/CD image publishing.

**Alternatives considered:**
- **Container registry + singularity pull on login node:** Deferred as unnecessary complexity for a single-user workflow. Can be adopted later without architectural changes.

## Existing Patterns

Investigation found the following existing patterns this design follows:

**Environment variable configuration:** `scripts/start_server.sh` reads `VLLM_MODEL`, `VLLM_TP`, `VLLM_GPU_MEM`, `VLLM_MAX_SEQS` from environment. The container entrypoint follows the same pattern — `hpc_env.sh` is the single source of runtime configuration.

**Health polling:** `scripts/process_corpus.sh` polls `localhost:$VLLM_PORT/health` with a 3600s timeout at 5s intervals. The container entrypoint replicates this pattern.

**EXIT trap cleanup:** `process_corpus.sh` uses `trap cleanup EXIT` to kill the tmux session. The container entrypoint uses the same pattern but kills a background process instead of a tmux session.

**CLI invocation:** The pipeline uses `llm-discovery process` and `llm-discovery import-results` Typer CLI commands. The container calls these identically.

**Divergences:**
- `start_server.sh` uses `uv run vllm serve` — inside the container, vLLM is installed globally, so `vllm serve` is called directly.
- `process_corpus.sh` uses tmux for vLLM — the container uses a background process instead (tmux is unnecessary inside a container).

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Apptainer Definition File and Entrypoint Script
**Goal:** Buildable `.sif` image that starts vLLM and responds on the health endpoint.

**Components:**
- `container/pipeline.def` — Apptainer definition file bootstrapping from `vllm/vllm-openai:v0.19.0`, copies project source via `%files`, installs llm-discovery in `%post`
- `container/entrypoint.sh` — orchestration script: source hpc_env.sh, validate required env vars, launch vLLM background, health poll, run process, run import-results, EXIT trap cleanup
- `container/hpc_env.rtx4090.sh` — example config for local RTX 4090 (Gemma 4 E4B, TP=1, mem=0.85)
- `container/hpc_env.gpuvolta.sh` — example config for Gadi V100 (Gemma 4 31B, TP=4, mem=0.90)
- `container/hpc_env.gpuhopper.sh` — example config for Gadi H200 (gpt-oss-120b, TP=4, mem=0.92)

**Dependencies:** None (first phase). Requires Apptainer installed locally and GPU available.

**Done when:** `sudo apptainer build pipeline.sif container/pipeline.def` succeeds. `apptainer exec --nv pipeline.sif vllm serve --help` returns usage. Container starts vLLM with a test hpc_env.sh pointing to Gemma 4 E4B and the health endpoint responds.
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: Local End-to-End Run
**Goal:** Container processes the demo corpus on RTX 4090, producing results.

**Components:**
- Test data directory with pre-built corpus.db, system_prompt.txt, hpc_env.sh (RTX 4090 config)
- Documentation for data directory preparation
- Verification that results appear in `out/` and are imported into corpus.db

**Dependencies:** Phase 1 (working container image)

**Done when:** Full pipeline runs inside the container: vLLM starts, processes all documents, imports results, exits 0. Results are readable from the host. This is DoD item 2.
<!-- END_PHASE_2 -->

<!-- START_PHASE_3 -->
### Phase 3: Deploy Automation Integration
**Goal:** Deploy command stages `.sif` to Gadi and submits PBS job using it.

**Components:**
- `stage_container_image()` in platform.py — replaces `build_remote_venv()`, scp's `.sif` to `/scratch/as07/containers/`, verifies sha256 checksum on remote after transfer
- Updated `generate_hpc_env()` — adds `HF_CACHE_DIR` and `CONTAINER_PATH` variables
- Updated PBS template — `module load singularity` + `singularity exec --nv` instead of direct script execution
- Updated `deploy()` CLI command — calls `stage_container_image()` instead of `build_remote_venv()`

**Dependencies:** Phase 2 (proven working container). Work happens in the gadi-deploy-automation worktree.

**Done when:** `llm-discovery deploy` stages the container image to Gadi and submits a PBS job that invokes the container. Existing deploy tests updated to reflect new staging path. This is DoD item 3.
<!-- END_PHASE_3 -->

<!-- START_PHASE_4 -->
### Phase 4: Gadi UAT
**Goal:** Job runs on Gadi, processes corpus, results retrieved.

**Components:**
- Pre-download Gemma 4 E4B model to `/scratch/as07/` HF cache on Gadi login node
- Submit job on gpuvolta queue
- Retrieve results via existing `retrieve_results()` function

**Dependencies:** Phase 3 (deploy automation working)

**Done when:** Job submitted on Gadi gpuvolta, corpus processed by container, results retrieved to local machine. This is DoD item 4 and the final UAT — human verification required.
<!-- END_PHASE_4 -->

## Additional Considerations

**Image versioning:** The `.sif` filename should include a version or build date (e.g., `pipeline-2026-04-12.sif`) so multiple versions can coexist on `/scratch`. The definition file is pinned to `vllm/vllm-openai:v0.19.0` — update the pin when new stable releases are verified.

**Shared memory:** vLLM uses shared memory for tensor parallel communication. Inside Singularity, `/dev/shm` size depends on host configuration. For TP=1 (RTX 4090, single GPU) this is not a concern. For TP=4 on Gadi V100s, monitor for shared memory errors — may need `--writable-tmpfs` flag.

**Ubuntu 24.04 Apptainer prerequisite:** Local builds require `kernel.apparmor_restrict_unprivileged_userns = 0` sysctl setting. This is a one-time setup step documented in the README.

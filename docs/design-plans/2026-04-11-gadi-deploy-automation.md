# Gadi Deploy Automation Design

**GitHub Issue:** None

## Summary

This design specifies a `deploy` command that fully automates running the document-classification pipeline on NCI Gadi. Today, deploying requires several manual steps: configuring environment variables on the remote, bootstrapping package management tooling, and ensuring model weights are pre-downloaded before a job consumes expensive GPU allocation. The new `deploy --platform gadi` command collapses all of that into a single invocation requiring only SSH access and a local HuggingFace token.

The implementation is a staged pipeline: local prerequisites are validated first (HuggingFace token, corpus preparation, config files), then the remote environment is staged over SSH (uv bootstrap, venv build, directory layout, environment file generation), then the target LLM's weights are pre-downloaded to scratch storage, and finally the PBS job is submitted. Each stage is idempotent — interrupted or re-run deploys skip already-completed work. The compute node, which accrues allocation cost, receives no network access and does no setup work; it sources a generated environment file and runs only inference and result import against a pre-built database.

## Definition of Done

`llm-discovery deploy --platform gadi --project <CODE> --gpu-queue <QUEUE>` is a single command that, given only SSH access and a valid project code:

1. Rsyncs the project (including a working venv) to `/scratch/<project>/llm-discovery/`
2. Ensures uv is available on the login node (installs if missing)
3. Builds/updates the venv on the login node with all deps + vLLM nightly
4. Ensures the HuggingFace model for the selected GPU tier is pre-downloaded to `/scratch/<project>/cache/`
5. Generates and deploys an `hpc_env.sh` with correct env vars: `HF_HOME`, `HUGGINGFACE_HUB_CACHE`, `VLLM_CACHE_ROOT`, `TORCH_HOME`, `HF_TOKEN`, `UV_PROJECT_ENVIRONMENT`, model selection, TP config — all pointing to `/scratch/<project>/` paths
6. The PBS job sources `hpc_env.sh` and runs entirely offline on the compute node
7. Fails fast with actionable errors if any prerequisite cannot be met

Compute allocation is expensive — the deploy must pre-validate as thoroughly as possible before submitting a PBS job, so allocation is not wasted on misconfigured runs.

## Acceptance Criteria

### gadi-deploy-automation.AC1: HF_TOKEN validated locally
- **gadi-deploy-automation.AC1.1 Success:** Deploy reads HF_TOKEN from environment and confirms it against the HuggingFace whoami API before any SSH operations
- **gadi-deploy-automation.AC1.2 Failure:** Missing or invalid HF_TOKEN produces "HF_TOKEN not set or failed whoami check" and exits before touching the remote

### gadi-deploy-automation.AC2: Corpus prepared locally
- **gadi-deploy-automation.AC2.1 Success:** Deploy runs fetch, prep-db, and preflight locally, producing a valid corpus.db
- **gadi-deploy-automation.AC2.2 Failure:** Preflight failures abort deploy with "Preflight failed — fix documents before deploying"

### gadi-deploy-automation.AC3: Remote environment staged
- **gadi-deploy-automation.AC3.1 Success:** uv is available on login node after deploy (installed if missing), venv is populated with all deps + vLLM nightly, cache directories exist under /scratch/<project>/
- **gadi-deploy-automation.AC3.2 Failure:** SSH failure produces "Cannot reach gadi.nci.org.au — check SSH keys"; missing /scratch produces "No /scratch access for project <CODE>"

### gadi-deploy-automation.AC4: Model pre-downloaded
- **gadi-deploy-automation.AC4.1 Success:** Model files for the selected GPU queue exist in /scratch/<project>/cache/huggingface/ after deploy
- **gadi-deploy-automation.AC4.2 Failure:** Download failure produces "Model download failed — check HF_TOKEN and disk quota"

### gadi-deploy-automation.AC5: hpc_env.sh generated correctly
- **gadi-deploy-automation.AC5.1 Success:** Generated hpc_env.sh contains HF_HOME, HUGGINGFACE_HUB_CACHE, VLLM_CACHE_ROOT, TORCH_HOME, HF_TOKEN, UV_PROJECT_ENVIRONMENT, model name, TP size, GPU memory, and max seqs — all correct for the selected queue

### gadi-deploy-automation.AC6: Compute node runs offline
- **gadi-deploy-automation.AC6.1 Success:** PBS job runs process + import-results using pre-staged venv and model with zero network calls
- **gadi-deploy-automation.AC6.2 Failure:** GPU count mismatch (nvidia-smi vs expected TP) produces error and aborts before starting vLLM

### gadi-deploy-automation.AC7: Idempotent re-run
- **gadi-deploy-automation.AC7.1 Success:** Re-running deploy skips already-completed stages (uv already installed, model already cached) and proceeds to submission

## Glossary

- **Gadi**: NCI's primary HPC supercomputer. Jobs run via PBS batch submission.
- **NCI**: National Computational Infrastructure; Australian government facility operating Gadi.
- **PBS**: Portable Batch System. Job scheduler on Gadi — jobs submitted with `qsub`, run on compute nodes when resources are available.
- **login node**: Internet-accessible SSH entry point to Gadi. Used for job preparation; has network access, unlike compute nodes.
- **compute node**: Machine inside the cluster where PBS jobs run. On Gadi, compute nodes have no internet access.
- **/scratch**: Gadi's parallel filesystem for project data, organised by project code. Files not accessed for 100 days are purged.
- **uv**: Fast Python package manager (Astral). Used instead of pip/virtualenv to manage dependencies.
- **fabric**: Python library for executing shell commands over SSH. Used in `platform.py` for remote operations.
- **vLLM**: Open-source LLM inference engine optimised for GPU throughput. Runs on compute nodes.
- **vLLM nightly**: Pre-release build of vLLM, required for Gemma 4 support.
- **HF_TOKEN**: HuggingFace API access token for downloading gated models. Validated locally before remote operations.
- **`hpc_env.sh`**: Shell environment file generated by deploy, written to remote. PBS job sources it for all cache paths, tokens, and model config.
- **TP / tensor parallelism**: Distributing a single model across multiple GPUs. TP size = number of GPUs used jointly.
- **`corpus.db`**: SQLite database built locally from input documents and prompts. Contains all data the compute node needs for inference.
- **whoami API**: HuggingFace endpoint (`/api/whoami-v2`) used to verify HF_TOKEN validity.
- **ABI compatibility**: Why the venv is built on the login node rather than shipped from the local machine — compiled extensions must match the remote architecture.

## Architecture

The deploy command is a staged pipeline of idempotent steps. Each stage checks whether its work is already done before acting; each fails fast with an actionable error message. No stage proceeds unless all prior stages succeeded.

```
Local machine                    Gadi login node              Gadi compute node
─────────────                    ───────────────              ─────────────────
1. Validate HF_TOKEN (API)
2. Build corpus.db locally
   (fetch → prep-db → preflight)
3. Check SSH connectivity  ────→ hostname
4. Check /scratch access   ────→ test -d /scratch/<project>
5. Rsync code + corpus.db  ────→ /scratch/<project>/llm-discovery/
6. Ensure uv               ────→ install if missing
7. Build venv              ────→ uv sync + vllm nightly
8. Pre-download model      ────→ huggingface-cli download
9. Generate hpc_env.sh     ────→ write to remote
10. Submit PBS job          ────→ qsub gadi.pbs
                                                              11. Source hpc_env.sh
                                                              12. module load cuda, python
                                                              13. Sanity check GPUs
                                                              14. Start vLLM (pre-staged)
                                                              15. process + import-results
                                                              16. EXIT trap kills vLLM
```

All internet-requiring operations (dependency install, model download) happen on the login node. The compute node is fully air-gapped.

### Key Components

- **`platform.py`** — `deploy_gadi()` function with staged steps, each a private method on a connection object. Existing `rsync_to_remote()` and `submit_gadi_job()` are refactored into this flow.
- **`hpc_env.sh`** (generated) — sourceable env file written to remote by deploy. Contains all cache paths, HF_TOKEN, model config, UV settings. PBS job sources this.
- **`hpc/gadi.pbs.template`** — updated to source `hpc_env.sh`, remove assumptions about pre-existing remote config.
- **`scripts/process_corpus.sh`** — simplified: no `uv sync`, no `prep-db`, no `preflight`. Only `process` + `import-results` against pre-built `corpus.db`.
- **`config/machines.yaml`** — existing GPU config, unchanged. Deploy reads model name, TP, memory settings from here.

### Data Flow

- `corpus.db` flows: local (fetch → prep-db → preflight) → rsync to remote → process on compute node → rsync back (retrieve command).
- `hpc_env.sh` flows: generated locally from `machines.yaml` + `platforms.yaml` + local env → written to remote via fabric.
- Model weights flow: HuggingFace Hub → login node cache (`/scratch/<project>/cache/huggingface/`) → compute node reads same path.

## Decision Record

### DR1: Staged idempotent steps over monolithic deploy
**Status:** Accepted
**Confidence:** High
**Reevaluation triggers:** If deploy becomes so fast that stage overhead matters; if stage boundaries create more bugs than they prevent.

**Decision:** We chose discrete, idempotent stages over a single linear function.

**Consequences:**
- **Enables:** Safe re-runs (interrupted deploy resumes where it left off), clear per-stage errors, testable units.
- **Prevents:** Nothing significant. Slightly more code than a monolithic function.

**Alternatives considered:**
- **Monolithic sequential function:** Rejected because partial failures leave ambiguous remote state and the function becomes unwieldy.

### DR2: Build corpus.db locally, not on remote
**Status:** Accepted
**Confidence:** High
**Reevaluation triggers:** If corpus size exceeds practical rsync limits (hundreds of MB); if prompts need to change between deploy and run.

**Decision:** We chose to run fetch, prep-db, and preflight locally and rsync the ready database, rather than shipping raw prompts/schema/input to the remote.

**Consequences:**
- **Enables:** Simpler compute node pipeline (just process + import). No need for prompts/, schema.sql, or input/ on remote. Local validation catches data issues before spending allocation.
- **Prevents:** Changing prompts on the remote without redeploying. (This is intentional — reproducibility requires the local machine to be the source of truth.)

**Alternatives considered:**
- **Ship prompts and build DB on compute node:** Rejected because it wastes compute time on non-GPU work and requires internet access for fetch.

### DR3: Hardcode GPU params from machines.yaml for Gadi
**Status:** Accepted
**Confidence:** High
**Reevaluation triggers:** If Gadi changes queue hardware without changing queue names; if auto-discovery becomes needed for a Gadi workflow.

**Decision:** We chose to read TP size, GPU memory, and model name from `config/machines.yaml` keyed by queue name, rather than discovering GPU config at runtime on the compute node.

**Consequences:**
- **Enables:** Pre-validation of config before job submission. Deterministic, reproducible runs.
- **Prevents:** Automatic adaptation if hardware changes. (Compute node does a sanity check — verifies GPU count matches expectation.)

**Alternatives considered:**
- **Runtime GPU discovery:** Reserved for UCloud design where GPU count is user-selectable.

### DR4: Push HF_TOKEN from local environment to remote
**Status:** Accepted
**Confidence:** High
**Reevaluation triggers:** If Gadi adopts a secrets management system; if HF_TOKEN rotation becomes frequent.

**Decision:** We chose to read HF_TOKEN from the local environment, validate it against the HuggingFace API, and write it into the generated `hpc_env.sh` on the remote — rather than requiring manual remote configuration.

**Consequences:**
- **Enables:** Fully automated deploy with zero manual remote setup (beyond SSH keys). Token validity confirmed before any remote operations.
- **Prevents:** Using different tokens on different machines without redeploying. (Intentional — single source of truth.)

**Alternatives considered:**
- **Require HF_TOKEN in remote ~/.bashrc:** Rejected because it requires manual SSH setup, contradicting the automation goal.

## Existing Patterns

Deploy already uses fabric for SSH (`platform.py`), subprocess for rsync, and Pydantic models for platform config (`PlatformConfig`). The new staged deploy follows the same patterns:

- fabric `Connection` for SSH commands (existing in `validate_platform()`, `submit_gadi_job()`)
- subprocess for rsync (existing in `rsync_to_remote()`)
- `config/platforms.yaml` for platform definitions (existing)
- `config/machines.yaml` for GPU params (existing, used by local runner)

The local pipeline stages (fetch, prep-db, preflight) are already implemented as library functions called by `cli.py` and `local_runner.py`.

`hpc_env.sh` generation follows the pattern from the FirstRun project (`/home/brian/people/Helle-Aarhus/20251104-FirstRun/hpc_setup.sh`) but is generated programmatically rather than maintained as a static file.

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Local Validation Stage
**Goal:** Validate all local prerequisites before touching the remote.

**Components:**
- HF_TOKEN validation in `src/llm_discovery/platform.py` — reads from environment, calls HuggingFace whoami API, fails with clear error
- Local corpus preparation — runs fetch, prep-db, preflight (reusing existing library functions from `fetch.py`, `prep_db.py`, `preflight_check.py`)
- Validation of local files: `config/platforms.yaml`, `config/machines.yaml`, `system_prompt.txt` exist

**Dependencies:** None (first phase)

**Done when:** `deploy --platform gadi` validates HF_TOKEN against the API, builds corpus.db locally, and fails with specific errors for each missing prerequisite.
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: Remote Environment Staging
**Goal:** Ensure uv, venv, and dependencies are ready on the Gadi login node.

**Components:**
- SSH connectivity check in `platform.py` — fabric connection test + `/scratch/<project>` existence
- uv bootstrap — `command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh` via SSH
- Directory creation — `/scratch/<project>/llm-discovery/` and `/scratch/<project>/cache/{huggingface/hub,vllm,torch}`
- Rsync update — push code + `corpus.db` + `system_prompt.txt` + `config/`, exclude `.venv/`, `.git/`, `input/`, `prompts/`, `out/`, `logs/`
- Remote venv build — `uv sync` + vLLM nightly install + transformers pin, all via SSH on login node
- `hpc_env.sh` generation — written to remote with all cache paths, HF_TOKEN, model config, UV settings

**Dependencies:** Phase 1 (local validation passes)

**Done when:** Login node has uv, a populated venv with vLLM, correct directory structure, and a generated `hpc_env.sh`.
<!-- END_PHASE_2 -->

<!-- START_PHASE_3 -->
### Phase 3: Model Pre-download
**Goal:** Ensure the HuggingFace model is cached on `/scratch` before job submission.

**Components:**
- Model download via SSH — `huggingface-cli download <model>` with cache env vars sourced from `hpc_env.sh`
- Model selection from `config/machines.yaml` based on GPU queue (gpuhopper → `openai/gpt-oss-120b`, gpuvolta → `google/gemma-4-31B-it`)

**Dependencies:** Phase 2 (venv with huggingface-cli exists, hpc_env.sh exists)

**Done when:** Model files exist in `/scratch/<project>/cache/huggingface/` on the login node. Deploy reports model size and confirms download.
<!-- END_PHASE_3 -->

<!-- START_PHASE_4 -->
### Phase 4: PBS Job Submission & Compute Node Pipeline
**Goal:** Submit PBS job that runs entirely offline using pre-staged resources.

**Components:**
- Updated `hpc/gadi.pbs.template` — sources `hpc_env.sh`, uses pre-staged venv, no internet operations
- Simplified `scripts/process_corpus.sh` — remove `uv sync`, remove `prep-db`, remove `preflight`. Add GPU sanity check (`nvidia-smi` count matches expected TP). Only runs `process` + `import-results`.
- PBS submission via fabric — existing `submit_gadi_job()` refactored into staged deploy flow

**Dependencies:** Phase 3 (model pre-downloaded)

**Done when:** PBS job submitted. Compute node runs process + import-results entirely offline, fails fast if GPU count mismatches.
<!-- END_PHASE_4 -->

<!-- START_PHASE_5 -->
### Phase 5: Documentation & Cleanup
**Goal:** Update all documentation to reflect automated deploy, remove references to manual remote setup.

**Components:**
- `docs/gadi-setup.md` — rewrite: SSH key setup is the only manual prerequisite. Everything else is automated by `deploy`.
- `docs/ucloud-setup.md` — replace manual steps with TODO placeholders (UCloud automation is a separate design).
- `README.md` — update Gadi quickstart to show the self-contained deploy command.
- Remove or update any other references to manual remote configuration.

**Dependencies:** Phase 4 (deploy flow works)

**Done when:** No documentation references manual remote setup for Gadi (except SSH keys). UCloud manual steps replaced with TODOs.
<!-- END_PHASE_5 -->

## Additional Considerations

**Error messages as documentation.** Every failure mode produces a message that tells the user what went wrong and what to do. These messages are the primary user-facing documentation for troubleshooting — they must be specific and actionable.

**Rsync excludes `.venv/`.** The venv is built on the login node (matching the remote architecture) rather than shipped from the local machine. The local machine may be a different OS/arch. `uv sync` on the login node ensures ABI compatibility.

**/scratch purge policy.** Gadi purges files not accessed for 100 days. Model cache and venv may be purged between infrequent runs. Deploy handles this by being idempotent — if the venv or model is missing, it rebuilds/redownloads.

**vLLM nightly pinning.** The vLLM nightly install is anchored to a specific version (currently `0.19.1rc1.dev203+g0f3ce4c74`) rather than pulling latest `--pre`. This prevents a broken nightly from silently breaking a deploy that previously worked. The pinned version is updated manually when a newer nightly is validated locally.

**Fabric PATH handling.** Fabric runs commands non-interactively without sourcing `.bashrc`. After installing uv, subsequent fabric commands must use the explicit path `$HOME/.local/bin/uv` rather than relying on `uv` being on PATH. All remote uv invocations use the full path.

**hpc_env.sh permissions.** The generated file contains HF_TOKEN. It is written with `chmod 600` to restrict access to the owning user only, since `/scratch/<project>/` is readable by all project members.

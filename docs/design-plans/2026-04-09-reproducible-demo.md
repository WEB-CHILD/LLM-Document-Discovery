# Reproducible Demo Pipeline Design

**GitHub Issue:** None

## Summary

This project builds a self-contained, reproducible pipeline for classifying historical web documents using a large language model. The pipeline takes archived web pages from the Internet Archive, converts them to markdown, runs them through a GPU-hosted LLM (gpt-oss-120b via vLLM), and stores classification results in a SQLite database. The result is a clean, cloneable repository that a reviewer or collaborator can run end-to-end without access to any private data or prior project infrastructure.

The orchestration layer is a Typer CLI (`llm-discovery`) that runs locally and manages the full workflow: fetching WARC records from the Internet Archive's CDX API, validating the remote HPC environment over SSH, syncing code and corpus via rsync, submitting jobs to either NCI Gadi (PBS scheduler) or UCloud (container-based REST API), and retrieving results. The core processing code — a streaming, crash-safe, resumable LLM classification engine — is carried forward from a previous production run (FirstRun) with minimal changes; the main new work is the CLI, the fetch pipeline, and the platform abstraction that makes the same pipeline portable across two HPC systems.

## Definition of Done

1. **`WEB-CHILD/LLM-Document-Discovery` repo** contains a clean, documented pipeline (no temp files, no embargoed data, no cruft from FirstRun) that someone with a HuggingFace account and GPU access can clone and run.

2. **Smoke test script** fetches 5 specific Kidlink/Kidpub pages from the Internet Archive, converts HTML to markdown, and runs the full pipeline end-to-end unattended.

3. **HPC job scripts**: a universal core runner with thin PBS (Gadi) wrapper and UCloud batch script, so the same pipeline runs on either system. Local orchestrator (`deploy_to_hpc.py` / CLI) handles environment validation, sync, and submission.

4. **Documentation**: README, setup instructions, and enough context for a reviewer or collaborator to understand and reproduce the pipeline.

## Acceptance Criteria

### reproducible-demo.AC1: Clean public repo
- **reproducible-demo.AC1.1 Success:** Clone + `uv sync` + `uv run llm-discovery --help` works with no manual setup beyond HF token
- **reproducible-demo.AC1.2 Success:** Repo contains no .db files, .jsonl files, sync-conflict files, or embargoed data
- **reproducible-demo.AC1.3 Failure:** `uv sync` on a machine without GPU still succeeds (vllm is optional runtime dep, not install-time)

### reproducible-demo.AC2: Smoke test fetch and process
- **reproducible-demo.AC2.1 Success:** `llm-discovery fetch` produces 5 markdown files with correct `{timestamp}/{url}` header format
- **reproducible-demo.AC2.2 Success:** Each fetched file passes `preflight_check` validation
- **reproducible-demo.AC2.3 Success:** Full pipeline (prep_db -> vLLM -> unified_processor -> import_results) completes on the 5 demo documents
- **reproducible-demo.AC2.4 Success:** `corpus.db` contains results for all 5 documents x 22 categories = 110 result_category rows
- **reproducible-demo.AC2.5 Failure:** `llm-discovery fetch` with unreachable IA URL reports clear error, does not leave partial files
- **reproducible-demo.AC2.6 Edge:** Re-running `llm-discovery fetch` skips already-fetched files (idempotent)

### reproducible-demo.AC3: HPC deployment
- **reproducible-demo.AC3.1 Success:** `llm-discovery deploy --platform gadi` rsyncs code and submits PBS job
- **reproducible-demo.AC3.2 Success:** `llm-discovery deploy --platform ucloud` either submits via API or prints clear manual instructions
- **reproducible-demo.AC3.3 Success:** `llm-discovery validate` reports pass/fail for each prerequisite (SSH, /scratch, HF_TOKEN, uv)
- **reproducible-demo.AC3.4 Failure:** `llm-discovery deploy` without prior `validate` warns and runs validation first

### reproducible-demo.AC4: Documentation
- **reproducible-demo.AC4.1 Success:** README contains quickstart that gets from clone to completed run in under 10 commands

## Glossary

- **Internet Archive (IA)**: A digital library that stores snapshots of web pages over time, accessible at archive.org.
- **WARC**: Web ARChive format. A standardised container format for storing web crawl data, including raw HTTP responses.
- **CDX API**: An index API provided by the Internet Archive. Given a URL, it returns metadata (timestamp, WARC filename, byte offset, length) needed to locate and download specific WARC records.
- **warcio**: A Python library for reading and writing WARC files. Used via `ArchiveIterator` to extract HTML from WARC records.
- **markdownify**: A Python library that converts HTML into Markdown.
- **vLLM**: An open-source LLM inference server that loads models onto GPU hardware and serves them via an OpenAI-compatible HTTP API.
- **gpt-oss-120b**: A 120B parameter open-source language model (5.1B active parameters) available on HuggingFace. Requires free account and licence acceptance.
- **Typer**: A Python library for building CLI applications with type annotations.
- **Rich**: A Python library for terminal output formatting (progress bars, status display).
- **datasette**: A Python tool for exploring SQLite databases through a web interface.
- **PBS / PBS Pro**: Portable Batch System — a job scheduler used on HPC clusters. Jobs submitted with `qsub`.
- **NCI Gadi**: Australia's National Computational Infrastructure flagship supercomputer. Uses PBS Pro with gpuvolta (V100), dgxa100 (A100), and H200 GPU queues.
- **UCloud**: A Danish HPC platform (DeiC). Uses a container-based web portal and REST API rather than PBS or SLURM.
- **ArchiveSpark pattern**: A data access pattern for the Internet Archive: query CDX index to locate specific WARC records, then download only those records via HTTP range requests.
- **Streaming processor architecture**: Design pattern in `unified_processor.py`: reader thread fetches unprocessed work from SQLite, bounded queues buffer it, worker threads process concurrently.
- **Atomic write (temp file + rename)**: Crash-safe file writing: write to temporary file, then rename (atomic on Unix).
- **SHA256 change detection**: Using content hashes to detect whether documents or prompts have changed since last processed.
- **tensor parallelism**: GPU parallelism strategy that splits model weights across multiple GPUs. Required for large models like gpt-oss-120b.
- **result_category**: A table in the pipeline schema representing the output of running one category prompt against one document. 110 rows = 5 documents x 22 categories.
- **Kidlink / Kidpub**: Historical online communities for children (1990s-2000s) whose archived pages serve as the demo corpus.
- **FirstRun**: The prior production run of this classification pipeline, from which core processing code is adapted.

## Architecture

### Overview

A Typer CLI (`llm-discovery`) that orchestrates the full pipeline from WARC retrieval through LLM classification to SQLite results. The CLI runs locally and manages remote HPC execution via SSH and platform-specific submission mechanisms.

```
Local machine (llm-discovery CLI)          Remote HPC (Gadi / UCloud)
────────────────────────────────          ─────────────────────────────
llm-discovery fetch                       
  → Download WARCs from IA                
  → warcio extract HTML                   
  → markdownify → input/demo_corpus/      
                                          
llm-discovery validate --platform gadi    
  → SSH probe /scratch, HF_TOKEN, uv     
                                          
llm-discovery deploy --platform gadi      
  → rsync code + corpus + prompts         → /scratch/{project}/llm-discovery/
  → qsub hpc/gadi.pbs                    → PBS allocates GPU node
                                            → scripts/process_corpus.sh
                                              → tmux: vLLM server (background)
                                              → prep_db.py → unified_processor.py
                                              → import_results.py → corpus.db
                                          
llm-discovery retrieve --platform gadi    
  → rsync corpus.db back                  
  → datasette corpus.db                   
```

### Components

**`src/llm_discovery/cli.py`** — Typer app. Subcommands: `fetch`, `validate`, `deploy`, `status`, `retrieve`, `run` (full pipeline). Platform selection via `--platform gadi|ucloud|local` flag or interactive prompt.

**`src/llm_discovery/fetch.py`** — WARC retrieval from Internet Archive following the ArchiveSpark pattern (CDX API → WARC download). For each URL: queries CDX API to get WARC `filename`, `offset`, `length`; downloads the specific WARC record via HTTP range request; extracts HTML with `warcio.ArchiveIterator`; converts to markdown with `markdownify`. Writes files with `{timestamp}/{url}` header line matching the existing corpus format. Default 5 Kidlink/Kidpub URLs hardcoded, overridable.

**Default demo URLs:**
- `https://web.archive.org/web/20040701020553/http://www.kidlink.org:80/KIDFORUM/`
- `https://web.archive.org/web/20040701022600/http://www.kidlink.org:80/KIDPROJ/Capitals97/introductions.html`
- `https://web.archive.org/web/20040701031153/http://www.kidlink.org:80/KIDPROJ/MCC/mcc0539.html`
- `https://web.archive.org/web/20040630084635/http://www.kidlink.org:80/spanish/`
- `https://web.archive.org/web/19970404181846/http://www.kidpub.org:80/kidpub/kidpub-newest.html`

**`src/llm_discovery/platform.py`** — Platform abstraction. Loads config from `config/platforms.yaml`. Handles SSH operations (validate, rsync, submit) per platform. Gadi: `qsub`. UCloud: REST API or manual web UI submission with instructions.

**`src/llm_discovery/unified_processor.py`** — Core LLM processing engine (from FirstRun). Streaming architecture: reader thread fetches unprocessed (result_id, category_id) pairs from SQLite, worker threads make HTTP requests to vLLM server, write atomic JSON files. Crash-safe and resumable.

**`src/llm_discovery/prep_db.py`** — Database setup. Creates SQLite from `schema.sql`, syncs documents from `input/`, syncs categories from `prompts/*.yaml`. SHA256 change detection for both. Large document splitting (>80KB) via RecursiveCharacterTextSplitter.

**`src/llm_discovery/preflight_check.py`** — Document validation. Rejects binary files, empty content, low printable character ratio. Logs exclusions with reason.

**`src/llm_discovery/import_results.py`** — JSON→SQLite import. Reads `r{id}_c{id}.json` output files, inserts result_category + blockquote rows. Idempotent via INSERT OR IGNORE.

**`scripts/process_corpus.sh`** — On-node orchestration. Starts vLLM in tmux session, waits for `/health`, runs processor in foreground, kills server via trap on EXIT. No `set -euo pipefail` — cleanup must always execute.

**`scripts/start_server.sh`** — vLLM server startup. Parameterised for model, GPU count, memory utilisation from environment variables.

**`hpc/gadi.pbs`** — PBS Pro directives for NCI Gadi. Requests gpuvolta queue, 4 GPUs, loads CUDA + Python modules, calls `scripts/process_corpus.sh`.

**`hpc/ucloud_batch.sh`** — UCloud Terminal app batch script. Runs in container environment (no module loading needed), calls `scripts/process_corpus.sh`.

**`config/platforms.yaml`** — Per-platform configuration: SSH host, filesystem paths (/scratch vs /work), module loading, submission mechanism, vLLM parameters.

**`config/machines.yaml`** — Per-GPU-type vLLM parameters: tensor parallelism, memory utilisation, max sequences. Keyed by GPU model (V100, A100, H100, H200).

**`prompts/*.yaml`** — 22 category definition files (inlined from former POC-prompts submodule). Each YAML contains category name, description, and LLM prompt. Multilingual (English, Danish, Korean).

### Data Flow

1. Internet Archive → WARC → HTML → markdown files in `input/demo_corpus/`
2. `prep_db.py` reads markdown files + `prompts/*.yaml` → populates `result` and `category` tables in SQLite
3. `preflight_check.py` validates documents, logs exclusions
4. vLLM server loads gpt-oss-120b model, serves OpenAI-compatible API on :8000
5. `unified_processor.py` streams unprocessed (result, category) pairs to vLLM, writes JSON output files atomically
6. `import_results.py` reads JSON files → inserts `result_category` and `result_category_blockquote` rows
7. Final `corpus.db` queryable via datasette or direct SQL

### On-Node Execution Model

```bash
# scripts/process_corpus.sh (no set -euo pipefail)
tmux new-session -d -s llm-server 'bash scripts/start_server.sh'
trap 'tmux kill-session -t llm-server 2>/dev/null' EXIT

while ! curl -s localhost:8000/health; do sleep 5; done

uv run python -m llm_discovery.prep_db
uv run python -m llm_discovery.preflight_check
uv run python -m llm_discovery.unified_processor
uv run python -m llm_discovery.import_results

# EXIT trap fires → server killed
```

vLLM server runs in tmux for log separation and debug access. Main process runs pipeline sequentially. Trap ensures server cleanup regardless of exit reason.

## Existing Patterns

### From FirstRun (adapted)

- **Streaming processor architecture**: Reader + bounded queue + worker threads. Validated at 384 concurrency on H100 GPUs. Carried forward as-is.
- **Atomic JSON writes**: temp file + rename pattern for crash safety. Proven in production runs.
- **SHA256 change detection**: Documents and prompts tracked by content hash for resumability. Preserved.
- **Per-file transaction scope**: All categories for one document committed atomically. Maintained.
- **Environment variable configuration**: All paths, model names, GPU params overridable via env vars. Extended with `config/platforms.yaml`.

### From Victor's JDH Article (adapted)

- **warcio ArchiveIterator**: For extracting HTML records from WARC data. Pattern visible in `warc_content_pie.py` cell of `article.ipynb`.
- **Timestamp/URL header format**: Markdown files prepend `{timestamp}/{url}` as first line. Standard across both the FirstRun corpus and the JDH article's methodology.

### New Patterns

- **Typer CLI with Rich TUI**: New to this project. Replaces shell script orchestration (`run_unattended.sh`, `runner.sh`, etc.) with structured subcommands.
- **Local orchestrator for remote HPC**: `deploy_to_hpc` pattern is new. FirstRun assumed you were already SSH'd into the HPC node.
- **Platform abstraction**: `config/platforms.yaml` + `platform.py` is new. FirstRun hardcoded paths for UCloud only.

## Implementation Phases

<!-- START_PHASE_1 -->
### Phase 1: Project Scaffolding

**Goal:** Clean repo structure with dependencies, installable package, and passing CI basics.

**Components:**
- `pyproject.toml` with dependencies: vllm, typer, rich, warcio, markdownify, requests, pydantic, pyyaml
- `src/llm_discovery/__init__.py` — package init
- `src/llm_discovery/cli.py` — Typer app skeleton with subcommand stubs
- `schema.sql` — copied from FirstRun
- `system_prompt.txt` — copied from FirstRun
- `prompts/*.yaml` — copied from FirstRun's POC-prompts submodule
- `.gitignore` — excludes *.db, *.jsonl, input/, *.log, __pycache__, .venv/
- `README.md` — stub with project name and "setup coming"

**Dependencies:** None (first phase)

**Done when:** `uv sync` succeeds, `uv run llm-discovery --help` shows subcommand list
<!-- END_PHASE_1 -->

<!-- START_PHASE_2 -->
### Phase 2: WARC Fetch Pipeline

**Goal:** `llm-discovery fetch` downloads 5 Kidlink/Kidpub pages from IA as WARC records, converts to markdown corpus.

**Components:**
- `src/llm_discovery/fetch.py` — CDX API query to locate WARC records (filename, offset, length), HTTP range request to download WARC data, warcio ArchiveIterator for HTML extraction, markdownify for HTML→markdown conversion, file writing with `{timestamp}/{url}` header format. Follows ArchiveSpark's CDX→WARC download pattern implemented in Python.
- CLI integration in `cli.py` — `fetch` subcommand with `--urls` override and Rich progress

**Dependencies:** Phase 1 (installable package)

**Done when:** `llm-discovery fetch` produces 5 markdown files in `input/demo_corpus/` with correct header format, content is valid markdown from the archived HTML
<!-- END_PHASE_2 -->

<!-- START_PHASE_3 -->
### Phase 3: Core Pipeline Integration

**Goal:** Database preparation, document processing, and results import working as package modules.

**Components:**
- `src/llm_discovery/prep_db.py` — adapted from FirstRun, updated imports, prompts path points to `prompts/`
- `src/llm_discovery/preflight_check.py` — adapted from FirstRun
- `src/llm_discovery/unified_processor.py` — adapted from FirstRun, updated imports
- `src/llm_discovery/import_results.py` — adapted from FirstRun
- `tests/` — adapted from FirstRun's test suite with updated imports

**Dependencies:** Phase 2 (demo corpus exists for testing)

**Done when:** `uv run python -m llm_discovery.prep_db` creates corpus.db from demo corpus, tests pass
<!-- END_PHASE_3 -->

<!-- START_PHASE_4 -->
### Phase 4: On-Node Execution Scripts

**Goal:** Shell scripts that run the full pipeline on a GPU node (server + processor + cleanup).

**Components:**
- `scripts/process_corpus.sh` — tmux server management, health wait, sequential pipeline, trap cleanup
- `scripts/start_server.sh` — parameterised vLLM server startup
- `config/machines.yaml` — vLLM parameters per GPU type (V100, A100, H100, H200)

**Dependencies:** Phase 3 (pipeline modules exist)

**Done when:** `bash scripts/process_corpus.sh` runs the full pipeline on a local GPU (or fails gracefully with clear error if no GPU available)
<!-- END_PHASE_4 -->

<!-- START_PHASE_5 -->
### Phase 5: Platform Configuration & Validation

**Goal:** `llm-discovery validate` checks remote HPC environment readiness.

**Components:**
- `src/llm_discovery/platform.py` — platform config loading, SSH probe, filesystem checks, env var validation
- `config/platforms.yaml` — Gadi and UCloud platform definitions (paths, modules, submission)
- CLI integration — `validate` subcommand with Rich status output

**Dependencies:** Phase 4 (knows what the remote needs to run)

**Done when:** `llm-discovery validate --platform gadi` reports pass/fail for SSH connectivity, /scratch space, HF_TOKEN, uv availability
<!-- END_PHASE_5 -->

<!-- START_PHASE_6 -->
### Phase 6: Deploy & Submit

**Goal:** `llm-discovery deploy` syncs code to HPC and submits job.

**Components:**
- Deploy logic in `platform.py` — rsync to correct remote paths, job submission
- `hpc/gadi.pbs` — PBS directives for gpuvolta queue, module loading, calls process_corpus.sh
- `hpc/ucloud_batch.sh` — UCloud container batch script, calls process_corpus.sh
- CLI integration — `deploy` subcommand, `status` subcommand (tail logs), `retrieve` subcommand (pull corpus.db)

**Dependencies:** Phase 5 (platform config and validation exist)

**Done when:** `llm-discovery deploy --platform gadi` rsyncs code and submits PBS job; `llm-discovery retrieve` pulls corpus.db back
<!-- END_PHASE_6 -->

<!-- START_PHASE_7 -->
### Phase 7: Full Run Orchestration

**Goal:** `llm-discovery run` executes the complete happy path interactively.

**Components:**
- `run` subcommand in `cli.py` — chains fetch → validate → deploy → status → retrieve with Rich prompts and progress
- `--platform local` mode — runs pipeline directly without SSH/rsync (for local GPU testing)
- Error handling and recovery prompts at each stage

**Dependencies:** Phase 6 (all subcommands exist)

**Done when:** `llm-discovery run --platform gadi` walks through entire pipeline from WARC fetch to corpus.db retrieval
<!-- END_PHASE_7 -->

<!-- START_PHASE_8 -->
### Phase 8: Documentation

**Goal:** README and supporting docs sufficient for a reviewer or collaborator to reproduce the pipeline.

**Components:**
- `README.md` — project overview, prerequisites (HF account, GPU access), quickstart (`llm-discovery run`), CLI reference, architecture overview
- `docs/` — architecture decisions carried from FirstRun, platform setup guides for Gadi and UCloud

**Dependencies:** Phase 7 (working pipeline to document)

**Done when:** A new collaborator can follow README from clone to completed demo run
<!-- END_PHASE_8 -->

## Additional Considerations

**UCloud is not SLURM.** UCloud uses a container-based web portal with REST API for job submission. Standard SLURM sbatch scripts do not work. The `deploy` subcommand for UCloud either calls the REST API directly or prints instructions for web UI submission. The batch script (`hpc/ucloud_batch.sh`) runs inside the container once the job is submitted. **Open risk:** UCloud REST API scriptability has not been verified. Implementation should include a spike (Phase 6) to test whether automated submission and status polling are feasible. If not, UCloud `deploy` falls back to rsync + manual web UI instructions.

**Error handling in process_corpus.sh.** No `set -euo pipefail` because the EXIT trap must always fire to kill the vLLM server. Each pipeline command runs sequentially in the foreground; failures are handled per-command (e.g., `|| exit 1`) rather than shell-wide. This is deliberate, not an oversight.

**Fetch defaults.** `llm-discovery fetch` defaults to the 5 Kidlink/Kidpub demo URLs. Accepts any set of IA URLs pasted as arguments, e.g., `llm-discovery fetch URL1 URL2 ...`. No separate fixture file — the defaults are in code, overridden by positional args.

**Model download latency.** gpt-oss-120b is large. First run on a new node requires downloading to /scratch. `scripts/start_server.sh` includes a health check timeout of up to 1 hour to accommodate this. The `validate` subcommand checks /scratch space before deployment.

**Demo scope vs production scope.** The CLI is designed around the 5-document demo but the architecture supports arbitrary corpus sizes. The `fetch` subcommand defaults to 5 pages but accepts any list of IA URLs. The processing pipeline is unchanged from FirstRun's production-validated code.

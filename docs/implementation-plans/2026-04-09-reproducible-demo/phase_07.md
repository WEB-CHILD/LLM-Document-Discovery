# Reproducible Demo Pipeline Implementation Plan

**Goal:** `llm-discovery run` executes the complete pipeline interactively or unattended. `--platform local` mode for direct GPU execution without SSH/rsync.

**Architecture:** The `run` subcommand chains: fetch → validate → deploy → status (poll) → retrieve. Interactive mode (default) prompts between stages. `--yes` flag enables fully unattended execution for overnight runs. `--platform local` bypasses SSH/rsync and runs the pipeline directly, managing vLLM server lifecycle via tmux.

**Tech Stack:** Typer, Rich (progress, prompts, status), tmux (for local mode vLLM server)

**Scope:** 8 phases from original design (phases 1-8)

**Codebase verified:** 2026-04-10

---

## Acceptance Criteria Coverage

This phase is integration of existing subcommands. No new ACs — it enables the complete workflow for AC2.3 (full pipeline completes) and AC3 (HPC deployment).

**Verifies: None** — verified operationally (full pipeline runs end-to-end).

---

<!-- START_TASK_1 -->
### Task 1: Implement `run` subcommand with interactive and unattended modes

**Files:**
- Modify: `src/llm_discovery/cli.py` (replace `run` stub)

**Implementation:**

Replace the `run` stub with:

```python
@app.command()
def run(
    platform: str = typer.Option("local", help="Platform: gadi, ucloud, or local"),
    project: str = typer.Option(None, help="NCI project code (for Gadi)"),
    gpu_queue: str = typer.Option("gpuhopper", help="Gadi GPU queue: gpuhopper or gpuvolta"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip interactive prompts (unattended mode)"),
    urls: list[str] = typer.Argument(None, help="Internet Archive URLs (defaults to demo)"),
) -> None:
    """Execute the complete pipeline: fetch -> validate -> deploy -> status -> retrieve."""
```

**Stage orchestration:**

1. **Fetch stage:**
   - Call the fetch logic (same as `llm-discovery fetch`)
   - Report: "Fetched N documents, skipped M"
   - If not `--yes`: prompt "Continue to deploy? [Y/n]"

2. **Platform-specific stages:**

   **If `--platform local`:**
   - Skip validate/deploy/retrieve
   - Start vLLM server in tmux (same pattern as `process_corpus.sh`)
   - Set EXIT trap to kill tmux session
   - Wait for health check
   - Run: prep-db → preflight → process → import-results
   - Kill server on completion
   - Report: "Pipeline complete. Results in corpus.db"

   **If `--platform gadi` or `--platform ucloud`:**
   - Validate (call validate logic)
   - If not `--yes`: prompt "Validation passed. Deploy? [Y/n]"
   - Deploy (rsync + submit)
   - Poll status every 60 seconds with Rich spinner
   - If not `--yes` and job completes: prompt "Retrieve results? [Y/n]"
   - Retrieve corpus.db

3. **Unattended mode (`--yes`):**
   - All prompts auto-answered "yes"
   - No interactive input required
   - Suitable for overnight runs, cron jobs, CI
   - Errors still cause non-zero exit

**Error handling at each stage:**
- If any stage fails: print error, skip remaining stages, exit 1
- If Ctrl+C: clean up (kill tmux if local, no orphan processes)

**Verification:**
Run: `uv run llm-discovery run --help`
Expected: Shows --platform, --project, --gpu-queue, --yes options

Run: `uv run llm-discovery run --platform local --yes --help`
Expected: Shows all options including --yes

**Commit:** `feat: implement full run orchestration with unattended mode`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Local mode vLLM server management

**Files:**
- Create: `src/llm_discovery/local_runner.py`

**Implementation:**

Extract local mode pipeline logic into a dedicated module. **Ownership note:** `local_runner.py` is the authoritative path for `--platform local` CLI runs. `scripts/process_corpus.sh` exists solely for HPC nodes where the CLI orchestrates remotely via SSH. They share the same tmux/health-check pattern but `local_runner.py` calls pipeline library functions directly (no subprocess), while `process_corpus.sh` calls CLI subcommands via shell.

1. **`start_vllm_server(model: str, gpu_params: dict, port: int = 8000) -> None`** — Start vLLM in tmux session `llm-server`. Uses subprocess calls to tmux (same pattern as `scripts/process_corpus.sh`).

2. **`wait_for_health(port: int = 8000, timeout: int = 3600) -> None`** — Poll `http://localhost:{port}/health` every 5 seconds. Raise RuntimeError on timeout.

3. **`stop_vllm_server() -> None`** — Kill tmux session `llm-server`. Called in finally/trap.

4. **`run_local_pipeline(db_path: Path, input_dir: Path, output_dir: Path, prompts_dir: Path, server_url: str) -> None`** — Run: prep-db → preflight → process → import-results. Calls the library functions directly (not subprocess), so errors propagate naturally.

**Testing:**
- Test health check polling with a mock HTTP endpoint
- Test tmux session cleanup logic
- Test that local_runner imports correctly

**Verification:**
Run: `uv run python -c "from llm_discovery.local_runner import run_local_pipeline; print('import OK')"`
Expected: Imports without error

**Commit:** `feat: add local mode vLLM server management`
<!-- END_TASK_2 -->

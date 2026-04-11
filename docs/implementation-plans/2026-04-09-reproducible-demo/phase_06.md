# Reproducible Demo Pipeline Implementation Plan

**Goal:** `llm-discovery deploy` syncs code to HPC and submits job. Gadi supports selectable GPU queues (gpuhopper default, gpuvolta). UCloud API spike determines whether automated submission is feasible.

**Architecture:** Deploy extends platform.py with rsync (subprocess) and job submission. Gadi uses PBS Pro via fabric SSH (`qsub`). UCloud submission determined by API spike — automated if feasible, manual instructions as fallback. PBS job script is parameterised for GPU queue selection. Retrieve pulls corpus.db back via rsync.

**Tech Stack:** fabric, subprocess (rsync), PBS Pro, Typer, Rich

**Scope:** 8 phases from original design (phases 1-8)

**Codebase verified:** 2026-04-10

---

## Acceptance Criteria Coverage

This phase implements and tests:

### reproducible-demo.AC3: HPC deployment
- **reproducible-demo.AC3.1 Success:** `llm-discovery deploy --platform gadi` rsyncs code and submits PBS job
- **reproducible-demo.AC3.2 Success:** `llm-discovery deploy --platform ucloud` either submits via API or prints clear manual instructions

---

<!-- START_TASK_1 -->
### Task 1: UCloud API spike

**Files:**
- None (investigation only — results inform Task 5)

**Implementation:**

Investigate UCloud's REST API for programmatic job submission:

1. **Research the UCloud API documentation** — find endpoints for:
   - Authentication (API tokens, OAuth)
   - Job/application submission
   - Job status polling
   - Available GPU resources listing

2. **Write a minimal Python script** (disposable, not committed) that attempts:
   - Authenticate with UCloud
   - List available applications/resources
   - Submit a trivial job (e.g., `echo hello`)
   - Poll job status

3. **Document findings:**
   - Is automated submission feasible?
   - What authentication is required?
   - What are the API endpoints and payload formats?
   - Any rate limits or restrictions?

4. **Decision gate:**
   - If API works: implement automated UCloud submission in Task 5
   - If API is insufficient or undocumented: implement rsync + manual web UI instructions in Task 5
   - Document the outcome either way

**Verification:**
Write a brief spike report (can be a comment in the code or a note in the PR) documenting what was found and the decision taken.

**No commit** — this is investigation work.
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Create hpc/gadi.pbs.template with selectable GPU queue

**Files:**
- Create: `hpc/gadi.pbs.template`

**Implementation:**

PBS Pro job template for NCI Gadi. **IMPORTANT: PBS does not expand shell variables in `#PBS` directives.** This file is a template with `{{PLACEHOLDER}}` markers that the deploy command substitutes at submission time using Python's `str.replace()` or `string.Template`. The deploy command writes a concrete `.pbs` file before calling `qsub`.

```bash
#!/bin/bash
#PBS -q {{GPU_QUEUE}}
#PBS -P {{NCI_PROJECT}}
#PBS -l ngpus=4
#PBS -l ncpus=48
#PBS -l mem=380GB
#PBS -l walltime=04:00:00
#PBS -l jobfs=200GB
#PBS -l storage=scratch/{{NCI_PROJECT}}
#PBS -N llm-discovery
#PBS -o llm-discovery.out
#PBS -e llm-discovery.err

# Load required modules
module load cuda/12.0
module load python3/3.12

# Change to working directory
cd "${PBS_O_WORKDIR}" || exit 1

# Set GPU-specific vLLM parameters based on queue
# These are read by scripts/process_corpus.sh -> scripts/start_server.sh
case "{{GPU_QUEUE}}" in
    gpuhopper)
        export VLLM_TP=4
        export VLLM_GPU_MEM=0.92
        export VLLM_MAX_SEQS=384
        ;;
    gpuvolta)
        export VLLM_TP=4
        export VLLM_GPU_MEM=0.90
        export VLLM_MAX_SEQS=64
        ;;
esac

export VLLM_MODEL="${VLLM_MODEL:-openai/gpt-oss-120b}"

# Run the pipeline
bash scripts/process_corpus.sh
```

**Template placeholders (substituted by deploy command):**
- `{{GPU_QUEUE}}` — GPU queue name (gpuhopper or gpuvolta)
- `{{NCI_PROJECT}}` — NCI project code

The deploy command reads this template, substitutes placeholders, writes `gadi.pbs` to the remote working directory, then calls `qsub gadi.pbs`.

**Verification:**
Run: `grep -c 'GPU_QUEUE' hpc/gadi.pbs.template`
Expected: 3 (in #PBS -q, case pattern, and case body comment)

Run: `grep -c 'NCI_PROJECT' hpc/gadi.pbs.template`
Expected: 2 (in #PBS -P and #PBS -l storage)

**Commit:** `feat: add Gadi PBS job template with selectable GPU queue`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Create hpc/ucloud_batch.sh

**Files:**
- Create: `hpc/ucloud_batch.sh`

**Implementation:**

UCloud container batch script. Runs inside the container environment (no module loading needed).

```bash
#!/usr/bin/env bash
# UCloud Terminal app batch script
# Run inside container with GPU access

# Set vLLM parameters for H100
export VLLM_MODEL="${VLLM_MODEL:-openai/gpt-oss-120b}"
export VLLM_TP=4
export VLLM_GPU_MEM=0.92
export VLLM_MAX_SEQS=384

cd /work/llm-discovery || exit 1

# Run the pipeline
bash scripts/process_corpus.sh
```

**Verification:**
Run: `bash -n hpc/ucloud_batch.sh`
Expected: No syntax errors

**Commit:** `feat: add UCloud batch script`
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Add deploy logic to platform.py

**Verifies:** reproducible-demo.AC3.1

**Files:**
- Modify: `src/llm_discovery/platform.py` (add deploy, retrieve functions)

**Implementation:**

Add deployment functions to platform.py:

1. **`rsync_to_remote(platform: PlatformConfig, local_dir: Path, project: str) -> None`** — rsync code to remote HPC. **No `--delete` flag** — remote may contain model cache, outputs, or other generated files that should not be removed by a code sync.
   ```python
   subprocess.run([
       "rsync", "-avz",
       "--exclude=.venv/", "--exclude=__pycache__/",
       "--exclude=*.db", "--exclude=*.pyc",
       "--exclude=.git/", "--exclude=input/",
       "--exclude=out/", "--exclude=*.log",
       str(local_dir) + "/",
       f"{platform.ssh_host}:{resolve_remote_path(platform, project)}/"
   ], check=True)
   ```

2. **`submit_gadi_job(platform: PlatformConfig, project: str, gpu_queue: str = "gpuhopper") -> str`** — Read `hpc/gadi.pbs.template`, substitute `{{GPU_QUEUE}}` and `{{NCI_PROJECT}}` placeholders, write the concrete `gadi.pbs` to the remote working directory via fabric `conn.put()`, submit via fabric `conn.run(f"cd {remote_path} && qsub gadi.pbs")`. Return job ID from qsub output.

3. **`submit_ucloud_job(platform: PlatformConfig) -> str | None`** — If UCloud API spike succeeded: submit via REST API. Otherwise: print manual instructions and return None.

4. **`retrieve_results(platform: PlatformConfig, local_dir: Path, project: str) -> Path`** — rsync corpus.db from remote to local. Return local path.

5. **`check_job_status(platform: PlatformConfig, job_id: str, project: str) -> str`** — For Gadi: `conn.run("qstat {job_id}")`. Parse output for status (Q/R/F/E).

**Testing:**
- Test rsync command construction (verify correct excludes)
- Test PBS template generation (GPU_QUEUE substitution)
- Test job ID parsing from qsub output

**Verification:**
Run: `uv run python -c "from llm_discovery.platform import submit_gadi_job; print('import OK')"`
Expected: Imports without error

**Commit:** `feat: add deploy, submit, and retrieve to platform module`
<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Implement UCloud submission (based on spike results)

**Verifies:** reproducible-demo.AC3.2

**Files:**
- Modify: `src/llm_discovery/platform.py` (implement submit_ucloud_job based on spike)

**Implementation:**

Based on Task 1 spike results:

**If API is feasible:**
- Implement `submit_ucloud_job()` using the discovered API endpoints
- Include authentication handling
- Return job ID for status polling
- Add UCloud status polling to `check_job_status()`

**If API is not feasible:**
- Implement `submit_ucloud_job()` to:
  1. rsync code to UCloud via SSH
  2. Print clear manual instructions with Rich formatting:
     ```
     UCloud automated submission not available.
     
     Manual steps:
     1. Open UCloud web portal at cloud.sdu.dk
     2. Create a new Terminal App job
     3. Select GPU: H100, 4 GPUs
     4. Mount /work/llm-discovery
     5. In terminal, run: bash scripts/process_corpus.sh
     ```
  3. Return None (indicating manual submission)

**Testing:**
- If API: test submission and status polling
- If manual: test that instructions are printed correctly

**Verification:**
Run: `uv run llm-discovery deploy --platform ucloud --help`
Expected: Shows deploy options

**Commit:** `feat: implement UCloud submission (API or manual fallback)`
<!-- END_TASK_5 -->

<!-- START_TASK_6 -->
### Task 6: Wire deploy, status, retrieve into CLI

**Verifies:** reproducible-demo.AC3.1, reproducible-demo.AC3.2

**Files:**
- Modify: `src/llm_discovery/cli.py` (replace deploy, status, retrieve stubs)

**Implementation:**

Replace the three stubs:

1. **deploy command:**
   ```python
   @app.command()
   def deploy(
       platform: str = typer.Option(..., help="HPC platform: gadi or ucloud"),
       project: str = typer.Option(None, help="NCI project code (for Gadi)"),
       gpu_queue: str = typer.Option("gpuhopper", help="Gadi GPU queue: gpuhopper or gpuvolta"),
   ) -> None:
       """Sync code to HPC and submit job."""
   ```
   - Run validation first (AC3.4 — warn if not validated)
   - rsync code to remote
   - Submit job (PBS for Gadi, API/manual for UCloud)
   - Print job ID and next steps

2. **status command:**
   ```python
   @app.command()
   def status(
       platform: str = typer.Option(..., help="HPC platform: gadi or ucloud"),
       job_id: str = typer.Option(None, help="Job ID to check"),
       project: str = typer.Option(None, help="NCI project code"),
   ) -> None:
       """Check status of running HPC job."""
   ```

3. **retrieve command:**
   ```python
   @app.command()
   def retrieve(
       platform: str = typer.Option(..., help="HPC platform: gadi or ucloud"),
       project: str = typer.Option(None, help="NCI project code"),
       output: Path = typer.Option("corpus.db", help="Local path for retrieved database"),
   ) -> None:
       """Pull results (corpus.db) back from HPC."""
   ```

**Testing:**
- Test deploy calls validation first
- Test that --gpu-queue option is passed through to PBS template
- Test that --help shows correct options for all 3 commands

**Verification:**
Run: `uv run llm-discovery deploy --help`
Expected: Shows --platform, --project, --gpu-queue options

Run: `uv run llm-discovery retrieve --help`
Expected: Shows --platform, --project, --output options

**Commit:** `feat: wire deploy, status, retrieve commands into CLI`
<!-- END_TASK_6 -->

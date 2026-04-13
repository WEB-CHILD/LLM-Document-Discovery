# Apptainer Pipeline Implementation Plan — Phase 4

**Goal:** Job runs on Gadi gpuvolta, processes corpus, results retrieved to local machine.

**Architecture:** Human-driven UAT using the deploy automation from Phase 3. Model weights pre-downloaded on Gadi login node. Data directory prepared on remote. Job submitted via `llm-discovery deploy`. Results retrieved via `llm-discovery retrieve`.

**Tech Stack:** Gadi PBS, Singularity, vLLM, HuggingFace Hub

**Scope:** Phase 4 of 4 from original design

**Codebase verified:** 2026-04-13

**Phase Type:** infrastructure

---

## Acceptance Criteria Coverage

This phase implements:

### apptainer-pipeline.AC4: Gadi UAT
- **apptainer-pipeline.AC4.1 Success:** PBS job completes on gpuvolta queue, results retrievable to local machine
- **apptainer-pipeline.AC4.2 Failure:** Job fails gracefully if model weights not pre-downloaded (`HF_HUB_OFFLINE=1` prevents hang)

---

## Prerequisites

Before starting this phase:
- Phase 3 completed: `llm-discovery deploy` stages container and submits PBS jobs
- `pipeline.sif` built locally (from Phase 1)
- Demo corpus prepared locally (from Phase 2)
- SSH access to `gadi.nci.org.au` configured
- NCI project code (as07) with gpuvolta allocation

---

## Bootstrap Note

First-time Gadi setup requires a specific ordering because of circular
dependencies:

- The container `.sif` must be on Gadi before you can download model weights
  (the download uses the container's Python to ensure cache format compatibility).
- Model weights must be cached before a PBS job can succeed
  (compute nodes have no internet, `HF_HUB_OFFLINE=1`).

The tasks below are ordered to handle this: deploy first (stages `.sif`,
submits a job that will fail — expected), download weights, prepare data,
then re-deploy for a working run.

---

<!-- START_TASK_1 -->
### Task 1: Initial deploy to stage container image on Gadi

The first deploy stages `pipeline.sif` to `/scratch/as07/containers/` via
rsync. It also submits a PBS job, which **will fail** — model weights are not
yet cached and data is not yet uploaded. This failure is expected.

**Step 1: Run deploy from local machine**

```bash
llm-discovery deploy --platform gadi --project as07 --gpu-queue gpuvolta
```

Expected output:
- "Syncing code to NCI Gadi..."
- "Staging container image pipeline.sif..." (rsync of ~8.5GB `.sif`)
- "Submitting PBS job to gpuvolta queue..."
- "Job submitted: XXXXXXX.gadi-pbs"

**Step 2: Verify container image is staged**

```bash
ssh gadi.nci.org.au "ls -lh /scratch/as07/containers/pipeline.sif"
```

Expected: File present, ~8.5GB.

The submitted job will fail. That is fine — we need the `.sif` on Gadi for
the next task (model download). The job failure does not need investigation.
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Pre-download model weights on Gadi login node

The container runs with `HF_HUB_OFFLINE=1`, so model weights must already
exist in the HuggingFace cache on Gadi. Login nodes have internet access;
compute nodes do not.

This task uses the `.sif` staged in Task 1 — running the download through the
container's Python ensures the `huggingface_hub` version writing the cache is
the same version that will read it during job execution.

**Step 1: SSH to Gadi and download the model**

```bash
ssh gadi.nci.org.au

# Create HF cache directory on scratch
mkdir -p /scratch/as07/hf_cache

# Set HF_TOKEN for gated models (Gemma 4 requires acceptance)
export HF_TOKEN="..."

# Download model weights using the container's Python environment
singularity exec \
    --bind /scratch/as07/hf_cache:/root/.cache/huggingface \
    /scratch/as07/containers/pipeline.sif \
    python3 -c "
from huggingface_hub import snapshot_download
snapshot_download(
    'google/gemma-4-E4B-it',
    ignore_patterns=['*.gguf'],
)
print('Download complete')
"
```

**Step 2: Verify model is fully cached**

```bash
ls -la /scratch/as07/hf_cache/models--google--gemma-4-E4B-it/
# Should show snapshots/ and blobs/ directories with model files
```

Expected: Model files present (~8GB for E4B).

**Step 3: Verify offline mode works using the container**

```bash
singularity exec \
    --bind /scratch/as07/hf_cache:/root/.cache/huggingface \
    --env HF_HUB_OFFLINE=1 \
    /scratch/as07/containers/pipeline.sif \
    python3 -c "
from huggingface_hub import snapshot_download
path = snapshot_download('google/gemma-4-E4B-it')
print(f'Model at: {path}')
"
```

Expected: Prints model path without network errors. If it fails with a
connection error, the model is not fully cached.
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Prepare and upload data directory

The data directory must contain corpus.db, system_prompt.txt, prompts/, and
hpc_env.sh before the container runs.

**Note:** Corpus data staging is intentionally a manual pre-step, not part of
the `deploy` CLI. The deploy command stages the container image and generates
hpc_env.sh (Phase 3), but corpus.db is project-specific data that changes
independently of deployments. The remote path must match
`resolve_remote_path()` output: `/scratch/{project}/llm-discovery/`.

**Step 1: Prepare data locally**

```bash
# On local machine, from repo root
bash scripts/prepare_container_data.sh data container/hpc_env.gpuvolta.sh
```

This creates `data/` with corpus.db, system_prompt.txt, prompts/, and
hpc_env.sh configured for V100 GPUs.

**Step 2: Upload data to Gadi**

The target path is `/scratch/as07/llm-discovery/data/` — this is
`resolve_remote_path(platform, "as07") + "/data/"`.

```bash
rsync -avz data/ gadi.nci.org.au:/scratch/as07/llm-discovery/data/
```

**Step 3: Verify on remote**

```bash
ssh gadi.nci.org.au "ls -la /scratch/as07/llm-discovery/data/"
```

Expected: corpus.db, system_prompt.txt, prompts/, hpc_env.sh, out/ all present.
<!-- END_TASK_3 -->

<!-- START_TASK_4 -->
### Task 4: Re-deploy and submit PBS job

With the container staged (Task 1), model weights cached (Task 2), and data
uploaded (Task 3), re-deploy to submit a job that should succeed.

**Step 1: Deploy**

```bash
llm-discovery deploy --platform gadi --project as07 --gpu-queue gpuvolta
```

The deploy command will re-stage the `.sif` (rsync is incremental — this is
fast since the file hasn't changed) and submit a new PBS job.

**Step 2: Monitor job status**

```bash
llm-discovery status --platform gadi --job-id XXXXXXX.gadi-pbs
```

Expected: Status transitions from "queued" → "running" → "finished".

The job may queue for some time depending on Gadi allocation availability.
Walltime is 4 hours.

**Step 3: Check job output on Gadi if needed**

```bash
ssh gadi.nci.org.au
cat /scratch/as07/llm-discovery/llm-discovery.out
cat /scratch/as07/llm-discovery/llm-discovery.err
cat /scratch/as07/llm-discovery/data/out/vllm.log
```

**If job fails:** Check `llm-discovery.err` for PBS errors. Check
`data/out/vllm.log` for vLLM startup failures. Common issues:
- Model not cached: "Cannot access gated repo" → re-run Task 2
- Shared memory: "shm" errors with TP=4 → add `--writable-tmpfs` to
  singularity exec in PBS template
- CUDA version mismatch: Check `module load cuda` version matches container's
  CUDA
<!-- END_TASK_4 -->

<!-- START_TASK_5 -->
### Task 5: Retrieve and verify results (AC4.1)

**Step 1: Retrieve results to local machine**

```bash
llm-discovery retrieve --platform gadi --project as07
```

Expected: corpus.db downloaded to local machine.

**Step 2: Verify results in database**

```bash
# Check result_category table has entries
sqlite3 corpus.db "SELECT COUNT(*) FROM result_category;"
# Should be > 0

# Check a sample of results
sqlite3 corpus.db "SELECT r.filepath, c.name, rc.match FROM result_category rc JOIN result r ON rc.result_id = r.id JOIN category c ON rc.category_id = c.id LIMIT 10;"
# Should show document-category pairs with match values (yes/maybe/no)

# Check blockquotes
sqlite3 corpus.db "SELECT COUNT(*) FROM result_category_blockquote;"
# Should be > 0

# Check run stats
sqlite3 corpus.db "SELECT * FROM run_stats;"
# Should show a completed run with hostname containing 'gadi'
```

**Step 3: Verify JSON output files were created**

```bash
ssh gadi.nci.org.au "ls /scratch/as07/llm-discovery/data/out/r*_c*.json | wc -l"
# Should be > 0, one file per (result_id, category_id) pair
```

**Step 4: Verify no orphaned processes**

```bash
ssh gadi.nci.org.au "pgrep -f 'vllm serve' || echo 'No orphaned vLLM processes'"
```

Expected: "No orphaned vLLM processes"

This verifies **apptainer-pipeline.AC4.1**: PBS job completed on gpuvolta,
results retrievable to local machine.
<!-- END_TASK_5 -->

<!-- START_TASK_6 -->
### Task 6: Verify offline failure mode (AC4.2)

**Step 1: Temporarily rename model cache to simulate missing weights**

```bash
ssh gadi.nci.org.au
mv /scratch/as07/hf_cache/models--google--gemma-4-E4B-it /scratch/as07/hf_cache/models--google--gemma-4-E4B-it.bak
```

**Step 2: Submit a test job**

```bash
llm-discovery deploy --platform gadi --project as07 --gpu-queue gpuvolta
```

**Step 3: Check that the job fails gracefully**

Wait for job to start, then check output:

```bash
ssh gadi.nci.org.au "cat /scratch/as07/llm-discovery/llm-discovery.err"
```

Expected: Error message about model not found or offline mode preventing
download. The job should exit non-zero without hanging.

This verifies **apptainer-pipeline.AC4.2**: Job fails gracefully if model
weights not pre-downloaded.

**Step 4: Restore model cache**

```bash
ssh gadi.nci.org.au
mv /scratch/as07/hf_cache/models--google--gemma-4-E4B-it.bak /scratch/as07/hf_cache/models--google--gemma-4-E4B-it
```
<!-- END_TASK_6 -->

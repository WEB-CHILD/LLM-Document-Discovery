# Reproducible Demo Pipeline Implementation Plan

**Goal:** Shell scripts that run the full pipeline on a GPU node: vLLM server lifecycle, sequential pipeline steps, crash-safe cleanup.

**Architecture:** `process_corpus.sh` orchestrates the on-node pipeline: installs GPU deps via `uv sync --extra gpu`, starts vLLM in tmux, waits for health, runs pipeline steps via Typer CLI (`llm-discovery prep-db` → `preflight` → `process` → `import-results`), kills server on EXIT trap. `start_server.sh` launches vLLM with GPU-specific parameters from `config/machines.yaml`.

**Tech Stack:** Bash, tmux, vLLM, uv, curl

**Scope:** 8 phases from original design (phases 1-8)

**Codebase verified:** 2026-04-10

---

## Acceptance Criteria Coverage

This phase is infrastructure. It enables AC2.3 (full pipeline completes) and AC3 (HPC deployment) but does not directly test acceptance criteria.

**Verifies: None** — verified operationally (scripts run, server starts, pipeline executes).

---

<!-- START_TASK_1 -->
### Task 1: Create config/machines.yaml

**Files:**
- Create: `config/machines.yaml`

**Implementation:**

Create GPU-specific vLLM parameter configuration. Adapt from FirstRun's `config/machines.yaml` at `/home/brian/people/Helle-Aarhus/20251104-FirstRun/config/machines.yaml`.

Structure:
```yaml
# vLLM parameters per GPU type
# Used by scripts/start_server.sh to configure tensor parallelism,
# memory utilisation, and concurrency limits.

gpu_types:
  V100:
    tensor_parallel_size: 4
    gpu_memory_utilization: 0.90
    max_num_seqs: 64
    notes: "NCI Gadi gpuvolta queue"

  A100:
    tensor_parallel_size: 4
    gpu_memory_utilization: 0.92
    max_num_seqs: 128
    notes: "NCI Gadi dgxa100 queue"

  H100:
    tensor_parallel_size: 4
    gpu_memory_utilization: 0.92
    max_num_seqs: 384
    notes: "UCloud or similar"

  H200:
    tensor_parallel_size: 4
    gpu_memory_utilization: 0.92
    max_num_seqs: 384
    notes: "NCI Gadi H200 queue"

# Default model
default_model: "openai/gpt-oss-120b"
```

Verify exact values against FirstRun's configuration. The tensor_parallel_size, gpu_memory_utilization, and max_num_seqs values are tuned from production experience.

**Verification:**
Run: `python -c "import yaml; print(yaml.safe_load(open('config/machines.yaml')))"`
Expected: Parses without error, shows all 4 GPU types

**Commit:** `feat: add GPU-specific vLLM configuration`
<!-- END_TASK_1 -->

<!-- START_TASK_2 -->
### Task 2: Create scripts/start_server.sh

**Files:**
- Create: `scripts/start_server.sh`

**Implementation:**

Adapt from FirstRun's `start_server_hpc.sh` at `/home/brian/people/Helle-Aarhus/20251104-FirstRun/start_server_hpc.sh`.

The script:
1. Reads environment variables: `VLLM_MODEL` (default: from machines.yaml), `VLLM_TP` (tensor parallelism), `VLLM_GPU_MEM` (memory utilisation), `VLLM_MAX_SEQS` (max concurrent sequences), `VLLM_PORT` (default: 8000)
2. Validates that required variables are set
3. Starts vLLM with the OpenAI-compatible API:
   ```bash
   uv run vllm serve "$VLLM_MODEL" \
     --tensor-parallel-size "$VLLM_TP" \
     --gpu-memory-utilization "$VLLM_GPU_MEM" \
     --max-num-seqs "$VLLM_MAX_SEQS" \
     --port "$VLLM_PORT" \
     --trust-remote-code
   ```
4. This script runs in foreground (called inside tmux by process_corpus.sh)

Make executable: `chmod +x scripts/start_server.sh`

**Verification:**
Run: `bash -n scripts/start_server.sh`
Expected: No syntax errors

**Commit:** `feat: add parameterised vLLM server startup script`
<!-- END_TASK_2 -->

<!-- START_TASK_3 -->
### Task 3: Create scripts/process_corpus.sh

**Files:**
- Create: `scripts/process_corpus.sh`

**Implementation:**

Adapt from FirstRun's `process_corpus.sh` and `run_unattended.sh` at `/home/brian/people/Helle-Aarhus/20251104-FirstRun/`.

**CRITICAL: No `set -euo pipefail`.** The EXIT trap must always fire to kill the vLLM tmux session.

The script:
```bash
#!/usr/bin/env bash
# On-node pipeline orchestration
# No set -euo pipefail — EXIT trap MUST always fire for server cleanup

# 1. Install GPU dependencies
uv sync --extra gpu

# 2. Read GPU config from environment (set by HPC job script)
# Required: VLLM_MODEL, VLLM_TP, VLLM_GPU_MEM, VLLM_MAX_SEQS
# Optional: VLLM_PORT (default 8000), DB_PATH (default corpus.db)

VLLM_PORT="${VLLM_PORT:-8000}"
DB_PATH="${DB_PATH:-corpus.db}"
INPUT_DIR="${INPUT_DIR:-input/demo_corpus}"
OUTPUT_DIR="${OUTPUT_DIR:-out}"

# 3. Start vLLM server in tmux session
tmux new-session -d -s llm-server "bash scripts/start_server.sh"

# 4. EXIT trap — cleanup server regardless of exit reason
trap 'tmux kill-session -t llm-server 2>/dev/null' EXIT

# 5. Wait for server health
echo "Waiting for vLLM server on port ${VLLM_PORT}..."
MAX_WAIT=3600  # 1 hour (model download can be slow on first run)
WAITED=0
while ! curl -sf "http://localhost:${VLLM_PORT}/health" > /dev/null 2>&1; do
    sleep 5
    WAITED=$((WAITED + 5))
    if [ "$WAITED" -ge "$MAX_WAIT" ]; then
        echo "ERROR: vLLM server did not start within ${MAX_WAIT}s"
        exit 1
    fi
done
echo "vLLM server is healthy"

# 6. Run pipeline sequentially via Typer CLI
uv run llm-discovery prep-db \
    --db "$DB_PATH" \
    --input-dir "$INPUT_DIR" || exit 1

uv run llm-discovery preflight \
    --db "$DB_PATH" || exit 1

uv run llm-discovery process \
    --db "$DB_PATH" \
    --output-dir "$OUTPUT_DIR" \
    --server-url "http://localhost:${VLLM_PORT}" || exit 1

uv run llm-discovery import-results \
    --db "$DB_PATH" \
    --input-dir "$OUTPUT_DIR" || exit 1

echo "Pipeline complete. Results in ${DB_PATH}"

# EXIT trap fires — server killed
```

Make executable: `chmod +x scripts/process_corpus.sh`

**Verification:**
Run: `bash -n scripts/process_corpus.sh`
Expected: No syntax errors

Run: `grep -c 'python -m' scripts/process_corpus.sh`
Expected: 0 (no python -m calls)

Run: `grep 'llm-discovery' scripts/process_corpus.sh`
Expected: 4 matches (prep-db, preflight, process, import-results)

**Commit:** `feat: add on-node pipeline orchestration script`
<!-- END_TASK_3 -->

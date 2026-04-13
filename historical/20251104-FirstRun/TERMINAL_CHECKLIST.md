# Terminal Checklist: Post-E05 GPU Validation

Run these commands after E05 HPC job completes to validate the refactor implementation.

---

## Quick Run-All Script (For Overnight Validation)

Paste this entire block into your terminal before bed. It will run everything and log results:

```bash
# Run all validation steps with logging
cd /home/brian/people/Helle/20251104-FirstRun && \
{
  echo "========================================"
  echo "Validation Started: $(date)"
  echo "========================================"
  echo ""

  # Set up environment
  echo "## Step 1: Setting up environment..."
  if [ -f .envrc.local ]; then
    source .envrc.local
  else
    echo "⚠️  .envrc.local not found, copying from example..."
    cp .envrc.local.example .envrc.local
    source .envrc.local
  fi
  echo ""

  # Check GPU
  echo "## Step 2: Checking GPU..."
  nvidia-smi || echo "❌ nvidia-smi failed (GPU not available?)"
  echo ""

  echo "## Step 3: Checking CUDA availability..."
  uv run python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU count: {torch.cuda.device_count()}')" || echo "❌ CUDA check failed"
  echo ""

  # Run all tests
  echo "## Step 4: Running all tests..."
  echo "This may take 1-2 minutes (model download on first run)..."
  echo ""
  uv run pytest tests/ -v --tb=short
  TEST_EXIT=$?
  echo ""

  # Summary
  echo "========================================"
  echo "Validation Completed: $(date)"
  echo "Test exit code: $TEST_EXIT"
  if [ $TEST_EXIT -eq 0 ]; then
    echo "✅ All tests PASSED"
  else
    echo "❌ Some tests FAILED (see output above)"
  fi
  echo "========================================"

  exit $TEST_EXIT
} 2>&1 | tee validation_results_$(date +%Y%m%d_%H%M%S).log
```

**What this does:**
- Sets up environment (creates `.envrc.local` if needed)
- Checks GPU availability
- Runs full test suite
- Logs everything to `validation_results_YYYYMMDD_HHMMSS.log`
- Shows summary at the end

**In the morning:** Check the log file:
```bash
# Find latest log
ls -lt validation_results_*.log | head -1

# View results
cat validation_results_*.log | tail -50
```

**Expected outcomes:**
- ✅ Best case: "✅ All tests PASSED" (23/23)
- ⚠️ Likely: Some GPU tests fail (need manual model download or GPU setup)
- ❌ Worst case: Environment issues (we'll debug based on log)

---

## 1. Check E05 Results on HPC (Optional - Do This First If You Want)

```bash
# SSH to HPC and check job results
cat /work/20251104-FirstRun/logs/e05_results_*.txt

# Check full log for timing details
tail -100 /work/20251104-FirstRun/logs/e05_vllm_test_*.log

# Expected: "Status: PASS" with cold start < 10 min
```

**Decision Point:**
- ✅ **PASS**: Continue with local GPU tests below
- ❌ **FAIL**: Debug E05 on HPC before proceeding locally

---

## 2. Set Up Local Environment Variables

```bash
# Navigate to project
cd /home/brian/people/Helle/20251104-FirstRun

# Copy and customize environment file
cp .envrc.local.example .envrc.local

# Source environment variables (sets HF_HOME, model paths, etc.)
source .envrc.local

# Should see:
# ✓ Local environment configured:
#   GPT_MODEL: openai/gpt-oss-20b
#   REASONING_EFFORT: Low
#   VLLM_TENSOR_PARALLEL_SIZE: 1
#   HF_HOME: /home/brian/.cache/huggingface
#   DB_PATH: ./corpus.db
```

**What this does:**
- Sets `HF_HOME`, `TRANSFORMERS_CACHE`, `TORCH_HOME` (proven pattern from document-corpus-llm-project)
- Creates cache directories
- Configures vLLM for single-GPU local use
- Sets model to gpt-oss-20b (faster for testing)

---

## 3. Verify Local GPU is Available

```bash
# Check NVIDIA driver
nvidia-smi

# Expected: Should show your GPU (RTX 4090 or similar)
```

```bash
# Check CUDA in Python
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU count: {torch.cuda.device_count()}')"

# Expected:
# CUDA available: True
# GPU count: 1
```

```bash
# Quick vLLM sanity check (will download model ~20-30 seconds if not cached)
python -c "from vllm import LLM; print('Initializing vLLM...'); llm = LLM(model='openai/gpt-oss-20b', tensor_parallel_size=1, gpu_memory_utilization=0.85, trust_remote_code=True); print('✓ vLLM works')"

# Expected: "✓ vLLM works" (may take 20-60s first time for model download)
```

**If GPU not available:**
- Check `nvidia-smi` shows the card
- Check CUDA drivers installed
- May need to wait for HPC results only (skip local GPU tests)

---

## 4. Run Non-GPU Tests (Quick Validation)

```bash
# Run configuration tests (no GPU needed)
uv run pytest tests/test_config.py -v

# Expected: 9/9 passed
```

```bash
# Run database tests (no GPU needed)
uv run pytest tests/test_database.py -v

# Expected: 6/6 passed
```

```bash
# Run harmony integration tests (non-GPU only)
uv run pytest tests/test_harmony_integration.py -v -m "not gpu"

# Expected: 6/6 passed
```

**Total so far:** 21 tests passed

---

## 5. Run GPU-Dependent Harmony Tests

```bash
# Full harmony test suite (includes GPU tests)
uv run pytest tests/test_harmony_integration.py -v

# Expected: 8/8 passed (including test_full_harmony_workflow and test_reasoning_effort_variations)
```

**What this validates:**
- vLLM model loads successfully
- Harmony token rendering works
- Response parsing extracts analysis + final channels
- Different reasoning efforts (Low/Medium/High) all work

**If failures occur:**
- CUDA OOM → Reduce `VLLM_GPU_MEMORY_UTILIZATION` in `.envrc.local` to 0.7
- Model download fails → Check internet connection, HF_HOME permissions
- Harmony parsing errors → Check `openai-harmony>=0.0.8` installed

---

## 6. Run Full Test Suite

```bash
# All tests together
uv run pytest tests/ -v

# Expected:
# test_config.py: 9 passed
# test_database.py: 6 passed
# test_harmony_integration.py: 8 passed
# TOTAL: 23 passed
```

**Checkpoint:** All infrastructure tests passing ✅

---

## 7. Report Results

If **all 23 tests pass**, you're ready to continue the refactor:

```bash
# In our conversation, say:
"All tests passed (23/23). Ready for Phase 6."
```

I'll then continue with:
- **Phase 6**: vLLM initialization function (`init_vllm_model()`)
- **Phase 7**: Batch processing (15 categories at once, using E04 pattern)
- **Phase 8**: Main integration (refactor `main.py` + `processor.py`)
- **Phases 9-12**: Error handling, performance validation, docs, production readiness

---

## 8. If Tests Fail

Capture the specific failure:

```bash
# Run failed test with verbose output
uv run pytest tests/test_harmony_integration.py::test_full_harmony_workflow -v -s

# Share the full error output in our conversation
```

Common issues:
- **GPU OOM**: Edit `.envrc.local`, set `VLLM_GPU_MEMORY_UTILIZATION=0.7`
- **Model not found**: Check `HF_HOME` is set correctly, check network
- **Import errors**: Run `uv sync` to ensure all dependencies installed
- **CUDA not available**: May need to run on HPC only

---

## Quick Summary

```bash
# The essential sequence:
source .envrc.local              # Set environment
nvidia-smi                        # Verify GPU
uv run pytest tests/ -v          # Run all tests (expect 23/23)
# Report: "All tests passed (23/23). Ready for Phase 6."
```

---

## Environment Variables Reference

After `source .envrc.local`, these are set:

**Model Configuration:**
- `GPT_MODEL=openai/gpt-oss-20b`
- `REASONING_EFFORT=Low`
- `VLLM_TENSOR_PARALLEL_SIZE=1`
- `VLLM_GPU_MEMORY_UTILIZATION=0.85`

**Cache Paths (proven pattern):**
- `HF_HOME=$HOME/.cache/huggingface`
- `TRANSFORMERS_CACHE=$HOME/.cache/huggingface/transformers`
- `TORCH_HOME=$HOME/.cache/torch`

**Python:**
- `PYTHONUNBUFFERED=1`
- `TOKENIZERS_PARALLELISM=false`

These match the working HPC setup from document-corpus-llm-project.

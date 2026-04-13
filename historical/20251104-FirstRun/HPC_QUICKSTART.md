# HPC Quick Start

**For current session on HPC** (after files transferred)

---

## 1. Load Environment (REQUIRED)

```bash
source /work/20251104-FirstRun/hpc_env.sh
```

**Verify**:
```bash
echo $VLLM_BASE  # Should show: /work/20251104-FirstRun/scratch
```

---

## 2. Run Tests

```bash
cd /work/20251104-FirstRun
bash run_tests_hpc.sh
```

**Expected**: 43 tests pass (35 non-GPU + 8 GPU)

---

## 3. Run 2-File Validation

```bash
# Quick validation with 2 documents
bash run_validation_2files.sh
```

**Expected**: 2 files processed, database populated, ~40-60s total time

---

## 4. Full Corpus Runs (Overnight)

**Recommended: Use run_full_corpus.sh** (no terminal required):

```bash
# Default: 20b model
nohup bash run_full_corpus.sh &

# Check progress
tail -f logs/full_corpus_*.log

# Or use watch_progress.sh (if available)
bash watch_progress.sh
```

**Alternative models** (set before running):
```bash
# 120b model (higher quality)
export GPT_MODEL="openai/gpt-oss-120b"
nohup bash run_full_corpus.sh &

# safeguard-20b (policy reasoning)
export GPT_MODEL="openai/gpt-oss-safeguard-20b"
nohup bash run_full_corpus.sh &
```

---

## Troubleshooting

### Environment not loaded
```bash
source /work/20251104-FirstRun/hpc_env.sh
```

### Cache conflicts
```bash
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
```

### Check GPU
```bash
nvidia-smi
```

---

## Configuration Notes

**Tensor Parallelism**: Default is `VLLM_TENSOR_PARALLEL_SIZE=1` (single GPU)
- gpt-oss-20b fits comfortably on one H100 (16-20GB of 80GB)
- TP>1 adds Ray overhead with no benefit for 20b model
- See [VLLM_RAY_ISSUE.md](VLLM_RAY_ISSUE.md) for technical details

**GPU Memory**: Using 90% utilization (72GB available for batching)

---

## File Transfer Summary

**New/Modified files to copy**:
- `hpc_env.sh` ⭐ NEW - Load environment variables (TP=1 default)
- `hpc_setup.sh` - Updated ending message
- `run_tests_hpc.sh` - Auto-loads environment
- `run_validation_2files.sh` ⭐ NEW - 2-file validation test
- `run_full_corpus.sh` ⭐ NEW - Overnight full corpus run
- `main.py`, `harmony_processor.py`, `pyproject.toml`
- `VLLM_RAY_ISSUE.md` ⭐ NEW - Technical documentation
- All `tests/*.py` files

**Delete on HPC**:
- `processor.py` (Ollama legacy)

# HPC Workflow - Step by Step

**Purpose**: Run vLLM pipeline on full markdown corpus with 20b model

---

## Files to Transfer

Copy these files to `/work/20251104-FirstRun/`:

### New Scripts
- `run_validation_2files.sh` - 2-file quick test
- `run_full_corpus.sh` - Overnight full corpus run
- `hpc_env.sh` - Environment variables (sourceable)

### Updated Files
- `main.py` - vLLM batch processing
- `harmony_processor.py` - Added batch extraction
- `pyproject.toml` - pytest configuration
- `hpc_setup.sh` - Adds env vars to .bashrc
- `run_tests_hpc.sh` - Auto-loads environment
- All `tests/*.py` files

---

## Execution Steps on HPC

### 1. Initial Setup (One Time Only)

```bash
cd /work/20251104-FirstRun

# Run setup script
bash hpc_setup.sh

# Load environment (REQUIRED)
source ~/.bashrc
# OR
source hpc_env.sh

# Verify environment loaded
echo $VLLM_BASE  # Should show: /work/20251104-FirstRun/scratch

# Sync dependencies
uv sync
```

---

### 2. Run Tests (Optional but Recommended)

```bash
# Run non-GPU tests (fast)
uv run pytest tests/ -v -m "not gpu"

# Skip GPU tests if they hang
```

**Note**: GPU tests may hang due to vLLM session state. Non-GPU tests (35 tests) validate all core logic.

---

### 3. Validate with 2 Files (5 minutes)

```bash
bash run_validation_2files.sh
```

**Success indicators**:
- Script completes without errors
- Output shows "Processing complete"
- Database has 2 results:
  ```bash
  sqlite3 corpus.db 'SELECT COUNT(*) FROM result;'  # Should be 2
  sqlite3 corpus.db 'SELECT COUNT(*) FROM result_category;'  # Should be 42 (2 files × 21 categories)
  ```

---

### 4. Run Full Corpus Overnight (20b model)

```bash
# Start overnight run (no terminal required)
nohup bash run_full_corpus.sh &

# Note the job number
# [1] 12345

# Detach from terminal (safe to logout)
```

---

### 5. Monitor Progress

```bash
# Check latest log
tail -f logs/full_corpus_gpt-oss-20b_*.log

# Or check database row count
watch -n 60 'sqlite3 corpus.db "SELECT COUNT(*) FROM result;"'

# Expected: ~1000 files (estimate)
# Speed: ~20-30s per file = ~6-9 hours total
```

---

### 6. Check Results

```bash
# View statistics
sqlite3 corpus.db <<EOF
SELECT 'Total Documents' as Metric, COUNT(*) as Count FROM result
UNION ALL
SELECT 'Total Category Results', COUNT(*) FROM result_category
UNION ALL
SELECT 'YES matches', COUNT(*) FROM result_category WHERE match='yes'
UNION ALL
SELECT 'MAYBE matches', COUNT(*) FROM result_category WHERE match='maybe'
UNION ALL
SELECT 'NO matches', COUNT(*) FROM result_category WHERE match='no';
EOF
```

---

## Model Selection

### 20b Model (Default - Recommended First)
```bash
# Already default in hpc_env.sh
nohup bash run_full_corpus.sh &
```
- **Speed**: ~20-30s per file
- **Quality**: Good for validation
- **Use case**: First full run to validate pipeline

### 120b Model (Higher Quality)
```bash
export GPT_MODEL="openai/gpt-oss-120b"
nohup bash run_full_corpus.sh &
```
- **Speed**: ~60-90s per file (estimate)
- **Quality**: Best reasoning
- **Use case**: Production quality results

### safeguard-20b (Policy Focus)
```bash
export GPT_MODEL="openai/gpt-oss-safeguard-20b"
nohup bash run_full_corpus.sh &
```
- **Speed**: ~20-30s per file
- **Quality**: Policy-aware reasoning
- **Use case**: Alternative interpretation

---

## Troubleshooting

### Environment not loaded
```bash
source /work/20251104-FirstRun/hpc_env.sh
echo $VLLM_BASE  # Verify
```

### Check if job is still running
```bash
jobs  # List background jobs
ps aux | grep python  # Check for Python process
```

### Kill hung job
```bash
jobs  # Note job number [1]
kill %1  # Kill job 1
```

### Database locked
```bash
# Only one process should write to corpus.db at a time
# If you need to query while processing:
sqlite3 corpus.db 'SELECT COUNT(*) FROM result;'  # Read-only is safe
```

### Out of memory
```bash
# Check GPU memory
nvidia-smi

# If OOM, reduce memory utilization
export VLLM_GPU_MEMORY_UTILIZATION="0.75"
nohup bash run_full_corpus.sh &
```

---

## File Locations

- **Input**: `/work/20251104-FirstRun/input/markdown_corpus/*.md`
- **Database**: `/work/20251104-FirstRun/corpus.db`
- **Logs**: `/work/20251104-FirstRun/logs/full_corpus_*.log`
- **Cache**: `/work/20251104-FirstRun/scratch/` (models, HF cache)

---

## Success Criteria

✅ 2-file validation completes successfully
✅ Full corpus run processes all files without errors
✅ Database has N results (N = number of .md files)
✅ Database has N × 21 category results
✅ Reasoning traces populated in result_category table
✅ Log file shows completion message with statistics

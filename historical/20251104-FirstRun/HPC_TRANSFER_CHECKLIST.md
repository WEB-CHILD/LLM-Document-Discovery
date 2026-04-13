# HPC Transfer Checklist

**Date**: 2025-11-15
**Status**: Ready for Transfer

---

## Files to Transfer to HPC

### Modified Core Files
- ✅ `main.py` - vLLM batch processing implementation
- ✅ `harmony_processor.py` - Added `extract_all_categories_batch()`
- ✅ `pyproject.toml` - Updated pytest configuration
- ✅ `hpc_setup.sh` - Adds environment variables to .bashrc

### Modified Test Files
- ✅ `tests/conftest.py` - Added temp_yaml_dir fixture, TP size env var support
- ✅ `tests/test_harmony_integration.py` - Updated max_tokens=512
- ✅ `tests/test_batch_processing.py` - New batch processing tests (3 GPU tests)
- ✅ `tests/test_main_functions.py` - New main function tests (14 non-GPU tests)

### New Helper Scripts
- ✅ `run_tests_hpc.sh` - Cache cleanup + pytest runner

### Documentation
- ✅ `docs/implementation/vllm_migration.md` - Migration guide

### Deleted Files
- ❌ `processor.py` - Ollama legacy code (delete on HPC too)

---

## HPC Setup Steps

### Step 1: Initial Setup (One Time)

```bash
# On HPC, in /work/20251104-FirstRun
bash hpc_setup.sh

# IMPORTANT: Load environment variables in current shell
source ~/.bashrc
# OR
source /work/20251104-FirstRun/hpc_env.sh

# Verify environment loaded
echo $VLLM_BASE  # Should show: /work/20251104-FirstRun/scratch
```

**This will**:
- Install CUDA toolkit
- Install uv
- Add persistent environment variables to ~/.bashrc
- Set up vLLM cache directories

**Note**: Environment variables are added to `.bashrc` permanently, but you must source it to activate in the current shell. Future logins will have them automatically.

### Step 2: Clean Old Cache

```bash
# Remove __pycache__ conflicts from Elaborations
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete
```

### Step 3: Sync Dependencies

```bash
uv sync
```

### Step 4: Run Tests

```bash
# Option A: Use helper script
bash run_tests_hpc.sh

# Option B: Manual
pytest tests/ -v -m "not gpu"  # 35 non-GPU tests
pytest tests/ -v -m gpu         # 8 GPU tests
```

---

## Expected Test Results

### Non-GPU Tests (35 tests)
- `test_config.py` - 9 tests
- `test_database.py` - 6 tests
- `test_harmony_integration.py` - 6 non-GPU tests
- `test_main_functions.py` - 14 tests

**All should PASS** ✅

### GPU Tests (8 tests)
- `test_harmony_integration.py` - 2 GPU tests
- `test_batch_processing.py` - 3 GPU tests
- *(Previously: 3 more from earlier work)*

**All should PASS on HPC with GPU** ✅

---

## Validation Workflow

### Phase 1: Test Suite (CURRENT STEP)
```bash
bash run_tests_hpc.sh
```
**Success criteria**: All 43 tests pass (35 non-GPU + 8 GPU)

### Phase 2: 10-File Validation
```bash
# Create test subset
mkdir -p /work/20251104-FirstRun/input/test_10files
cp $(ls /work/20251104-FirstRun/input/markdown_corpus/*.md | head -10) \
   /work/20251104-FirstRun/input/test_10files/

# Run on test subset
export INPUT_DIR="/work/20251104-FirstRun/input/test_10files"
export GPT_MODEL="openai/gpt-oss-20b"
python main.py
```

**Success criteria**:
- All 10 files processed
- Database has reasoning_trace populated
- No errors
- Performance ~20-30s per file

### Phase 3: Full Corpus Runs

**20b model** (validation):
```bash
export GPT_MODEL="openai/gpt-oss-20b"
python main.py
```

**120b model** (production quality):
```bash
export GPT_MODEL="openai/gpt-oss-120b"
python main.py
```

**safeguard-20b** (policy reasoning):
```bash
export GPT_MODEL="openai/gpt-oss-safeguard-20b"
python main.py
```

---

## Environment Variables

These are automatically added to `.bashrc` by `hpc_setup.sh`:

```bash
# vLLM cache and storage
export VLLM_BASE="/work/20251104-FirstRun/scratch"
export HF_HOME="$VLLM_BASE"
export HUGGINGFACE_HUB_CACHE="$VLLM_BASE/hub"
export VLLM_CACHE_ROOT="$VLLM_BASE/cache"

# Model configuration (defaults, can override)
export GPT_MODEL="${GPT_MODEL:-openai/gpt-oss-20b}"
export VLLM_TENSOR_PARALLEL_SIZE="${VLLM_TENSOR_PARALLEL_SIZE:-2}"
export VLLM_GPU_MEMORY_UTILIZATION="${VLLM_GPU_MEMORY_UTILIZATION:-0.85}"
export REASONING_EFFORT="${REASONING_EFFORT:-Medium}"

# Project paths
export WORK_DIR="/work/20251104-FirstRun"
export INPUT_DIR="$WORK_DIR/input/markdown_corpus"
export DB_PATH="$WORK_DIR/corpus.db"
```

**Override example**:
```bash
GPT_MODEL=openai/gpt-oss-120b python main.py
```

---

## Troubleshooting

### Issue: pytest collects tests from submodules
**Solution**: Already fixed - `pyproject.toml` now has `testpaths = ["tests"]`

### Issue: "ImportError: No module named 'ollama'"
**Solution**: Submodule tests excluded, but if seen, run cache cleanup

### Issue: "__pycache__ conflicts"
**Solution**: Run `find . -name "__pycache__" -type d -exec rm -rf {} +`

### Issue: GPU OOM
**Solution**: Reduce `VLLM_GPU_MEMORY_UTILIZATION` to 0.7

### Issue: Tests hang
**Solution**: Check vLLM initialization logs, verify CUDA available

---

## Success Indicators

✅ **Tests Pass**: All 43 tests (35 non-GPU + 8 GPU)
✅ **10-file run**: Completes without errors
✅ **Database populated**: reasoning_trace column has content
✅ **Performance**: ~20-30s per file on 20b model
✅ **All models work**: 20b, 120b, safeguard-20b all complete successfully

---

## Files Summary

**Total modified**: 10 files
**Total created**: 3 files
**Total deleted**: 1 file (processor.py)

**Lines of code**:
- `main.py`: 357 lines (complete rewrite)
- `harmony_processor.py`: +75 lines (batch function)
- `tests/test_main_functions.py`: 209 lines (new)
- `tests/test_batch_processing.py`: 156 lines (new)

**Test coverage**: 43 tests validating all components

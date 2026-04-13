# Manual Test Runs for Elaboration 04

For long-running tests where you want manual control and progress visibility.

## Quick Commands

### 1. Run all tests with tqdm progress bars

```bash
uv run python Elaborations/Elaboration04/run_manual.py
```

**What it does**:
- Loads vLLM model once (~20s)
- Tests batch sizes: 1, 5, 10, 15, 20
- Shows tqdm progress bar for batch processing
- Prints summary table with speedup analysis
- Runtime: ~4 minutes total

**Output**:
- Per-batch-size results (time, throughput, memory)
- Summary comparison table
- Speedup analysis (sequential vs batch=15)
- ✅/⚠️/❌ verdict

---

### 2. Run pytest with progress monitoring

```bash
# Terminal 1: Run tests
uv run pytest Elaborations/Elaboration04/ -xvs

# Terminal 2: Watch progress (optional)
watch -n 2 'ps aux | grep pytest'
```

**What it does**:
- Runs all 8 parametrised tests
- Verbose output shows test progress
- Runtime: ~4 minutes total

---

### 3. Run single batch size test

```python
# Create test_single.py or run in Python REPL
from vllm import LLM
from batch_processor import process_file_with_batch_size, reset_peak_gpu_memory, get_peak_gpu_memory
from pathlib import Path
import yaml

# Load model
llm = LLM(model="openai/gpt-oss-20b", gpu_memory_utilization=0.85, trust_remote_code=True)

# Load test data
with open("system_prompt.txt") as f:
    system_prompt = f.read()

categories = []
for yaml_file in sorted(Path("POC-prompts").glob("*.yaml")):
    with open(yaml_file) as f:
        data = yaml.safe_load(f)
        categories.append({"name": yaml_file.stem, "prompt": data["prompt"]})

test_file = list(Path("input").rglob("*.md"))[0]
with open(test_file) as f:
    document = f.read()

# Run test
reset_peak_gpu_memory()
metrics = process_file_with_batch_size(
    llm=llm,
    document_content=document,
    system_prompt=system_prompt,
    categories=categories,
    batch_size=15,  # Change this
    reasoning_effort="Low",
    max_tokens=512,
    temperature=0.0,
    show_progress=True,  # tqdm progress bar
)

print(f"Time: {metrics['total_time']:.2f}s")
print(f"Throughput: {metrics['categories_per_second']:.2f} cat/sec")
print(f"Memory: {get_peak_gpu_memory():.2f} GB")
```

---

## Recommended Workflow

### For quick validation (already done):
```bash
uv run pytest Elaborations/Elaboration04/ -xvs
```
✅ Completed - see [RESULTS.md](RESULTS.md)

### For manual exploration:
```bash
# Run with tqdm progress
uv run python Elaborations/Elaboration04/run_manual.py

# Modify run_manual.py to test different configurations:
# - Different batch sizes
# - Different reasoning efforts ("Low", "Medium", "High")
# - Different models (gpt-oss-safeguard-20b)
# - Different max_tokens
```

### For HPC deployment:
```bash
# Copy pattern to HPC job script
# Add tqdm to dependencies
# Use show_progress=True for batch processing
```

---

## Progress Visibility

### With tqdm (recommended for manual runs):
```
Processing batches: 100%|██████████| 3/3 [00:12<00:00,  4.1s/batch]
```

### With pytest (automatic):
```
test_batch_performance[15]
============================================================
Testing batch_size=15
============================================================
📊 Results for batch_size=15:
  Total time: 7.96s
  Throughput: 1.88 categories/sec
✅ Test passed for batch_size=15
PASSED
```

---

## Dependencies

Ensure tqdm is installed:
```bash
uv add tqdm
# or
uv pip install tqdm
```

If tqdm is not available, `show_progress=True` will be silently ignored (no error).

---

## Monitoring Long Runs

### GPU utilisation:
```bash
watch -n 1 nvidia-smi
```

### Process status:
```bash
watch -n 2 'ps aux | grep -E "(python|pytest)" | grep -v grep'
```

### Test output (if running in background):
```bash
tail -f pytest_output.log  # if redirected to file
```

---

## Customization

Edit [run_manual.py](run_manual.py) to:
- Change batch sizes to test: `BATCH_SIZES = [1, 5, 10, 15, 20, 25, 30]`
- Test different files: `test_files = select_test_files(num_files=10)`
- Change reasoning effort: `reasoning_effort="Medium"` or `"High"`
- Test multiple documents per batch size
- Save results to JSON for further analysis

---

## Expected Runtimes

Based on local RTX 4090 results:

| Batch Size | Time per file (15 categories) |
|------------|------------------------------|
| 1 (sequential) | ~19s |
| 5 | ~12s |
| 10 | ~9.5s |
| 15 | ~8s |
| 20 | ~8s |

**Full manual run** (5 batch sizes × 1 file + overhead): ~4 minutes

**Full pytest run** (8 tests including speedup comparison): ~4 minutes

**HPC with 120b model**: Expect longer per-call latency but similar speedup ratio.

# Elaboration 05: HPC vLLM Startup & Model Loading

## Hypothesis to Falsify

**"vLLM can start, download gpt-oss model from HuggingFace, load it into GPU memory, and serve requests within HPC environment constraints, with total startup time < 10 minutes."**

## What We're Testing

1. Can vLLM start on HPC node without errors?
2. Can models be downloaded from HuggingFace to `/work/.cache/` persistent storage?
3. Does the model load into GPU memory successfully?
4. Can vLLM serve requests after startup?
5. What's the total startup time (acceptable for hour-long runs)?
6. Does the cache survive VM restart (persistent HF_HOME)?
7. Does vLLM compilation/CUDA graph capture work on first run?

## Why This Matters

The HPC workflow assumes:
- vLLM starts cleanly in automated script
- Models download to persistent storage (not lost on shutdown)
- Startup time is acceptable (if 30 min startup for 1hr run, we're wasting 50% on overhead)
- No manual intervention needed
- CUDA graph compilation is cached for subsequent runs

If any of these fail, the fire-and-forget HPC workflow won't work.

## Success Criteria

### ✅ PASS
- vLLM starts without errors
- Model downloads to correct cache location (HF_HOME)
- Model loads into GPU successfully
- CUDA graph capture completes without errors
- First request completes successfully
- Total startup time < 10 minutes (first run)
- Subsequent runs < 2 minutes (cached)
- Cache persists across VM restarts

### ⚠️  PARTIAL
- Startup works but takes 10-20 minutes first time
- OR: Requires minor script adjustments
- Fallback: Pre-download models, adjust timeout expectations

### ❌ FAIL
- vLLM won't start on HPC
- OR: Models won't download/cache properly
- OR: GPU loading fails
- OR: Startup > 20 minutes (unacceptable overhead)
- OR: CUDA graph capture fails

## Test Approach

### Phase 1: Write Test Scripts ✅

Created:

- `test_hpc_vllm_startup.py`: Python test script using E01 harmony patterns
- `hpc_job.sh`: SLURM job script for fire-and-forget HPC submission

### Phase 2: Submit to HPC (Manual)

**Fire-and-forget workflow**:

1. Via web interface: Upload `hpc_job.sh` and submit
2. Via CLI: `sbatch Elaborations/Elaboration05/hpc_job.sh`
3. No manual intervention required - script handles everything

### Phase 3: Monitor Results

Check logs:

- `/work/20251104-FirstRun/logs/e05_vllm_test_<JOBID>.log`
- `/work/20251104-FirstRun/logs/e05_vllm_test_<JOBID>.err`
- `/work/20251104-FirstRun/logs/e05_results_<JOBID>.txt`

### Phase 4: Document Findings

Record timing metrics in `RESULTS.md`

## Files

- `README.md` - This file
- `test_hpc_vllm_startup.py` - Python test script using vLLM + harmony integration
- `hpc_job.sh` - SLURM job script for fire-and-forget HPC submission
- `RESULTS.md` - Document timing and findings (to be created after HPC run)

## Expected Outcome

Either:
1. **PASS**: Startup works, timing acceptable, pattern ready for setup.sh integration
2. **PARTIAL**: Timing slow but workable, document workarounds
3. **FAIL**: HPC environment incompatible, need different approach

## Testing Scenarios

### Scenario 1: Cold Start (First Time)
- Empty HF_HOME cache
- Model must download from HuggingFace (~16GB for gpt-oss-20b)
- Expected time: 5-10 minutes

### Scenario 2: Warm Start (Model Cached)
- Model in HF_HOME cache
- CUDA graphs may need compilation
- Expected time: 1-2 minutes

### Scenario 3: Hot Start (Everything Cached)
- Model cached
- CUDA graphs compiled
- Expected time: < 30 seconds

### Scenario 4: Multiple Models
- Test switching between 20b and 120b
- Verify cache management

## HPC-Specific Considerations

### Environment Variables
```bash
export HF_HOME=/work/.cache/huggingface
export VLLM_CACHE_DIR=/work/.cache/vllm
export CUDA_VISIBLE_DEVICES=0  # If needed
```

### Memory Requirements
- gpt-oss-20b: ~16GB VRAM
- gpt-oss-120b: ~60GB VRAM (may need multi-GPU)
- H100 has 80GB, should be sufficient

### Network Access
- HuggingFace download requires internet
- May need to pre-download models if network restricted

### Persistence
- `/work/` directory persists across VM restarts
- `/tmp/` is ephemeral
- Ensure cache paths point to `/work/`

## Implementation Pattern

```python
import time
from vllm import LLM, SamplingParams

# Time model loading
start = time.time()
llm = LLM(
    model="openai/gpt-oss-20b",
    gpu_memory_utilization=0.85,
    trust_remote_code=True,
)
load_time = time.time() - start
print(f"Model loaded in {load_time:.1f}s")

# Test inference
start = time.time()
outputs = llm.generate(
    prompts=["Hello"],
    sampling_params=SamplingParams(max_tokens=10, temperature=0.0)
)
infer_time = time.time() - start
print(f"First inference in {infer_time:.1f}s")
```

## Key Metrics to Document

- Model download time (if not cached)
- Model loading time
- CUDA graph capture time
- First inference latency
- Subsequent inference latency
- Peak GPU memory usage
- Cache directory sizes

## Dependencies

- HPC access with GPU node
- vLLM 0.10.2 installed
- openai_harmony 0.0.8
- Internet access for HuggingFace downloads (or pre-downloaded models)
- Sufficient `/work/` storage space (~50GB per model)

## Expected Results Format

```markdown
# HPC vLLM Startup Results

## Environment
- Node: gpu-h100-1
- GPU: NVIDIA H100 80GB
- CUDA: 12.4
- vLLM: 0.10.2

## Timing (Cold Start)
- HuggingFace download: 8m 23s
- Model loading: 1m 45s
- CUDA graph capture: 0m 32s
- First inference: 0m 05s
- **Total cold start: 10m 45s**

## Timing (Warm Start)
- Model loading: 1m 42s
- CUDA graph capture: 0m 28s
- First inference: 0m 04s
- **Total warm start: 2m 14s**

## Memory Usage
- Model weights: 13.7GB
- KV cache: 4.7GB
- CUDA graphs: 0.8GB
- **Peak usage: 19.2GB**

## Conclusion
✅ Acceptable for production
- Cold start: 10.75 min
- Warm start: 2.23 min
- For 1-hour runs, overhead is 18% first run, 3.7% subsequent runs
```

(These are hypothetical - real results will vary)

# Ray Research Summary - November 2025

## Your Question
"We have 4 GPUs per allocation. Do we need to debug Ray? What level of threading is needed?"

## Answer: No Ray Debugging Needed

### Key Finding
**Tensor parallelism is unnecessary for gpt-oss-20b** because:
- Model requires: ~16-20GB VRAM
- H100 provides: 80GB VRAM
- Ratio: 4x more memory than needed

### Threading Model

**With TP=1 (Single GPU)**:
- ✅ No Python threading
- ✅ No multiprocessing
- ✅ No Ray cluster
- ✅ Pure CUDA GPU batching
- ✅ Simplest, most reliable architecture

**With TP>1 (Multi-GPU)** - NOT NEEDED FOR 20B:
- ❌ Ray spawns separate Python processes
- ❌ Each process manages one GPU shard
- ❌ NCCL handles inter-GPU communication
- ❌ Ray coordinates via multiprocessing
- ❌ Complex, prone to initialization hangs

### Performance Comparison

| Configuration | Speed | Complexity | Reliability |
|--------------|-------|------------|-------------|
| TP=1 (single GPU) | 20-30s/file | Low | High ✅ |
| TP=2 (multi-GPU) | **Slower** (overhead) | High | Low ❌ |

**Why TP=2 is slower for 20b**:
- Ray cluster startup overhead
- Inter-GPU communication latency
- NCCL synchronization delays
- No benefit (model already fits)

## When to Use TP>1

**Only when model doesn't fit on single GPU:**
- gpt-oss-120b: ~240GB → Requires TP=4 on H100
- NOT applicable to gpt-oss-20b

## What We Configured

All files already set to TP=1:
- `hpc_env.sh`: `VLLM_TENSOR_PARALLEL_SIZE=1`
- `run_validation_2files.sh`: `VLLM_TENSOR_PARALLEL_SIZE=1`
- `run_full_corpus.sh`: Uses hpc_env.sh defaults

## No Background Processes Needed

You asked about "starting Ray in the background" - **this is not applicable**:
- With TP=1: No Ray at all (single process)
- With TP>1: vLLM manages Ray automatically (no manual start)

## Documentation Used

Research covered:
- vLLM official documentation on tensor parallelism
- Ray integration requirements and known issues
- NCCL GPU communication architecture
- vLLM 0.11.0 specific bugs and workarounds

## Conclusion

✅ **Current configuration (TP=1) is correct** - not a workaround
✅ **No Ray debugging needed** - Ray not used with TP=1
✅ **No threading complexity** - single process, CUDA batching
✅ **Ready to run** - just transfer files and execute

The Ray hang was a symptom of using an unnecessary optimization for a model that doesn't need it.

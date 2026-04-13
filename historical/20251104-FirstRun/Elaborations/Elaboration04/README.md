# Elaboration 04: Batch Processing Performance (vLLM)

## Hypothesis to Falsify

**"Processing 15 categories in a single vLLM batch is faster than sequential processing, with vLLM's native GPU batching providing optimal throughput."**

## What We're Testing

1. Is sequential processing (one category at a time) actually slow?
2. Does vLLM batch processing provide significant speedup?
3. What's the optimal batch size for our use case?
4. Does vLLM handle 15 concurrent prompts efficiently?
5. What's the speedup factor compared to sequential (2x, 4x, more)?
6. Is batch_size=15 (all categories at once) optimal or should we use smaller batches?

## Why This Matters

The refactor assumes vLLM batch processing of 15 categories will be faster than any other approach.
If this is FALSE, we need to reconsider our processing strategy.

We need to know:
- Whether vLLM batching provides real speedup
- Optimal batch size configuration
- Memory requirements for batching
- Whether the complexity is justified

## Success Criteria

### ✅ PASS
- Batch processing shows significant speedup (>3x) over sequential
- vLLM handles 15-prompt batches without errors
- GPU utilization is high during batch processing
- Memory requirements are acceptable
- Clear optimal batch size identified

### ⚠️  PARTIAL
- Modest speedup (2-3x) - might be worth it
- OR: Speedup exists but memory-constrained
- Fallback: Use smaller batches or sequential processing

### ❌ FAIL
- No speedup or slower than sequential
- OR: vLLM can't handle batch sizes we need
- OR: Memory requirements are prohibitive

## Test Approach

### Phase 1: Write Failing Tests (pytest)
Create `test_batch_performance.py` with tests that:
1. Measure sequential vLLM processing time (one prompt at a time)
2. Measure batch processing at different sizes (5, 10, 15 prompts)
3. Compare throughput and latency
4. **These tests will FAIL if batch processing is slower or broken**

### Phase 2: Confirm Test Can Falsify
Run pytest and verify it can detect performance regressions

### Phase 3: Implement Batch Processing
Modify harmony_integration.py to support batch operations

### Phase 4: Verify Tests Pass & Extract Optimal Config
Re-run tests to find optimal batch size

## Files

- `README.md` - This file
- `test_batch_performance.py` - Performance benchmarks (write first)
- `batch_processor.py` - Implementation (stub first, implement after tests)
- `RESULTS.md` - Document test results

## Expected Outcome

Either:
1. **PASS**: Clear speedup with optimal batch size documented
2. **PARTIAL**: Marginal speedup, document tradeoffs
3. **FAIL**: No speedup, fall back to sequential

## Key Performance Metrics

### Throughput
- Categories processed per second
- Tokens per second (input + output)

### Latency
- Time per file with batching vs sequential
- Time to first token (TTFT) for batch
- Time per output token (TPOT)

### Resource Utilization
- GPU memory usage for different batch sizes
- GPU utilization percentage
- Peak memory requirements

### Scalability
- Performance with batch sizes: 1, 5, 10, 15, 20
- Point of diminishing returns

## Testing Scenarios

### Scenario 1: Baseline Sequential
- Process 5 real files sequentially
- 15 categories per file = 75 total vLLM calls
- One prompt at a time
- Measure total time

### Scenario 2: Batch Size = 5
- Same 5 files, batch 5 categories at a time
- 3 batches per file
- Expect ~3-4x speedup

### Scenario 3: Batch Size = 10
- Same 5 files, batch 10 categories at a time
- 2 batches per file
- Expect ~5-7x speedup

### Scenario 4: Batch Size = 15
- Same 5 files, batch all 15 categories together
- 1 batch per file (optimal)
- Expect ~8-10x speedup

### Scenario 5: Batch Size = 20
- Over-provisioning test
- May hit memory limits or diminishing returns

## Dependencies

- Elaboration 01 must PASS (need working vLLM + harmony integration)
- vLLM 0.10.2 with openai_harmony 0.0.8
- At least 5 real markdown files for testing
- Sufficient GPU memory (test with gpt-oss-20b first)

## Variables to Control

- Model (use openai/gpt-oss-20b for consistency)
- Reasoning effort (use "Low" for speed)
- File size (use subset of files ~same size)
- Temperature (0.0 for determinism)
- max_num_seqs (vLLM batch size parameter)

## Expected Results to Document

```markdown
# Batch Processing Results (vLLM)

## Configuration
- Model: openai/gpt-oss-20b
- Reasoning: Low
- Files tested: 5
- Categories per file: 15
- GPU: NVIDIA H100

## Results

| Batch Size | Total Time | Categories/sec | Speedup | GPU Util | Peak Memory |
|------------|-----------|----------------|---------|----------|-------------|
| 1 (seq)    | 300s      | 0.25           | 1.0x    | 40%      | 16GB        |
| 5          | 90s       | 0.83           | 3.3x    | 70%      | 18GB        |
| 10         | 50s       | 1.50           | 6.0x    | 85%      | 20GB        |
| 15         | 35s       | 2.14           | 8.6x    | 90%      | 22GB        |
| 20         | 40s       | 1.88           | 7.5x    | 85%      | 24GB        |

## Conclusion
Optimal batch size: 15 (all categories in one batch)
Speedup: 8.6x over sequential
Recommendation: Use batch_size=15 for production
GPU memory requirement: 22GB peak
```

(These are hypothetical - real results will vary)

## Why vLLM Native Batching

- **Native GPU parallelism** - vLLM processes multiple prompts simultaneously on GPU
- **Memory efficiency** - Shared KV cache across batch, PagedAttention optimization
- **High throughput** - No Python threading overhead, pure GPU scheduling
- **Simple implementation** - Single `llm.generate()` call, no executor management
- **Predictable performance** - Deterministic GPU scheduling, no thread contention

## Implementation Pattern

```python
# Batch all 15 categories for one file
prefill_batch = []
for category in categories:
    prefill_ids, stop_ids = construct_harmony_conversation(
        system_prompt, category['prompt'], document, "Low"
    )
    prefill_batch.append(TokensPrompt(prompt_token_ids=prefill_ids))

# Single vLLM call processes all 15 prompts
outputs = llm.generate(prompts=prefill_batch, sampling_params=params)

# Parse all responses
results = [parse_harmony_response(out.outputs[0].token_ids) for out in outputs]
```

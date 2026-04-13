# Elaboration 06: vLLM Server Mode + HTTP API

**Date**: 2025-11-16
**Status**: 🔄 In Progress

## Hypothesis

"vLLM server mode with HTTP API can preserve harmony format (analysis + final channels), handle parallel requests efficiently, and solve the CUDA OOM issue from in-process `LLM()` usage."

## Context

Current implementation uses `from vllm import LLM` to load the model in-process. After 4 minutes of processing, we hit CUDA OOM. Moving to server-based architecture should provide:
- Better memory isolation
- Ability to restart client without reloading model
- Natural handling of parallel requests
- Better suited for HPC deployment

## Prior Art (E01)

Elaboration 01 proved:
- ✅ vLLM 0.10.2 with `LLM()` class works with harmony tokens
- ✅ `openai_harmony` properly renders conversations to token IDs
- ✅ Analysis and final channels parse correctly from output tokens
- ✅ gpt-oss-20b produces valid structured output

**Question**: Can we preserve this over HTTP?

## Test Plan

### Phase 1: Harmony Format Preservation (CRITICAL)

**Hypothesis**: vLLM's Responses API supports harmony channels over HTTP

**Test**:
1. Start `vllm serve openai/gpt-oss-20b --tensor-parallel-size 2`
2. Use `OpenAI` client with Responses API endpoint
3. Send harmony-style instructions
4. Verify we get analysis/final channel separation

**Success Criteria**: Response contains structured reasoning + output
**Failure Mode**: Channels not separated → document limitation

### Phase 2: Parallel Request Handling

**Hypothesis**: Server handles 15 concurrent requests without OOM

**Test**:
1. Send 15 parallel requests using `asyncio.gather()` + `AsyncOpenAI`
2. Monitor GPU memory via `nvidia-smi`
3. Measure TTFT, total latency, throughput

**Success Criteria**: All 15 complete, memory stable
**Failure Mode**: OOM or deadlock → determine max concurrency

### Phase 3: Multi-File Stress Test

**Hypothesis**: Server mode doesn't accumulate memory across files

**Test**:
1. Process 10 files sequentially (15 requests each = 150 total)
2. Monitor GPU memory after each file
3. Check for memory leaks or accumulation

**Success Criteria**: Memory returns to baseline between files
**Failure Mode**: Memory grows → investigate cleanup

### Phase 4: Refactor Implementation (Conditional)

**Only proceed if Phases 1-3 pass**

Create HTTP-based version of `harmony_processor.py`:
1. Duplicate current implementation
2. Replace `llm.generate()` with `AsyncOpenAI` client calls
3. Reuse conversation construction from E01
4. Test with 2-3 real files

**Deliverables**:
- `harmony_processor_http.py`
- Performance comparison table
- Updated config for server URL

## Success Criteria

1. ✅ Harmony format preserved over HTTP (or limitation documented)
2. ✅ 15 parallel requests complete without OOM
3. ✅ Memory stable across multiple files
4. ✅ Throughput >= current implementation
5. ✅ Working HTTP-based processor (if 1-3 pass)

## Failure Scenarios

### If Harmony Not Supported
- Document limitation clearly
- Propose alternative: structured outputs with reasoning as text field
- Update E01 pattern to show both approaches

### If OOM Persists
- Determine max concurrent requests
- Document memory limits
- Consider chunked processing strategy

### If Memory Accumulates
- Investigate server-side cache settings
- Test with `--no-enable-prefix-caching`
- Document cleanup requirements

## Files

- `README.md` - This file
- `test_http_harmony.py` - Phase 1 tests
- `test_http_parallel.py` - Phase 2 tests
- `test_http_stress.py` - Phase 3 tests
- `harmony_processor_http.py` - Phase 4 implementation
- `RESULTS.md` - Outcomes and patterns
- `conftest.py` - Shared test fixtures

## Cross-References

- [E01 Results](../Elaboration01/RESULTS.md) - In-process vLLM with harmony
- [vLLM Guide](../../docs/external/vllm_guide.md) - Responses API documentation
- [Current Implementation](../../harmony_processor.py) - In-process version
- [CLAUDE.md Decision #14](../../CLAUDE.md#decision-14) - vLLM backend selection

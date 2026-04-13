# vLLM vs Ollama: Backend Selection

**Author**: Claude + Brian
**Date**: 2025-11-14
**Status**: Active decision

## Decision

Use **vLLM** as the primary inference backend for HPC deployment.

## Context

gpt-oss models can run with multiple inference backends:
- Ollama (consumer-focused)
- vLLM (server-focused)
- Transformers (direct PyTorch)

We need to choose the right backend for our HPC workflow processing 7,466 documents.

## Comparison

| Aspect | vLLM | Ollama |
|--------|------|--------|
| **Target Use Case** | Servers, HPC, batch processing | Consumer hardware, local dev |
| **GPU Support** | Multi-GPU, H100 optimized | Single GPU, consumer cards |
| **Batch Processing** | Native batching, PagedAttention | Sequential processing |
| **Harmony Format** | Proper token rendering required | Chat template (mimics harmony) |
| **API** | OpenAI-compatible + direct sampling | Chat API only |
| **Setup Complexity** | Moderate (pip install) | Easy (single binary) |
| **Performance** | High throughput | Good latency |
| **Memory Efficiency** | PagedAttention (efficient KV cache) | Standard caching |

## Use Cases

### When to Use vLLM

✅ **HPC deployment** (our primary use case)
- Multi-GPU nodes (H100s)
- Batch processing thousands of files
- Need maximum throughput
- Server environment

✅ **Production workloads**
- High concurrent requests
- Need batching
- Resource optimization critical

### When to Use Ollama

✅ **Local development**
- Single developer machine
- Testing prompts
- Quick iterations

✅ **Consumer hardware**
- Mac with Apple Silicon
- Gaming PC with single GPU
- No server setup wanted

## Technical Differences

### Harmony Format Handling

**vLLM** (proper implementation):
```python
from openai_harmony import load_harmony_encoding
from vllm import LLM

encoding = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS)
prefill = encoding.render_conversation_for_completion(convo, Role.ASSISTANT)

llm = LLM(model="openai/gpt-oss-20b")
outputs = llm.generate(prompt_token_ids=[prefill], ...)

messages = encoding.parse_messages_from_completion_tokens(tokens, Role.ASSISTANT)
```

**Ollama** (approximation):
```python
import ollama

# Ollama applies chat template automatically
# No direct token control
response = ollama.chat(
    model="gpt-oss:20b",
    messages=[{"role": "system", "content": "..."}, ...]
)
```

### Batching

**vLLM**:
```python
# Process 15 categories at once
prefills = [render_convo(cat1), render_convo(cat2), ...]
outputs = llm.generate(prompt_token_ids=prefills)  # Parallel on GPU
```

**Ollama**:
```python
# Must use threading for parallelism
with ThreadPoolExecutor(max_workers=15) as executor:
    futures = [executor.submit(ollama.chat, ...) for _ in range(15)]
```

## Performance Implications

### For Our Workload

**7,466 files × 15 categories = 111,990 LLM calls**

**vLLM (estimated)**:
- Batch size: 15 (all categories for one file)
- Time per batch: ~30 seconds
- Total: ~7,466 × 30s ≈ 62 hours

**Ollama (estimated)**:
- Sequential: ~15 × 30s = 450s per file
- With threading (8 workers): ~120s per file
- Total: ~7,466 × 120s ≈ 249 hours

**Speedup**: ~4x with vLLM batching

## Migration Path

### Phase 1: Local Development (Ollama)
- Quick setup
- Test prompts
- Validate logic
- **Status**: Completed in Elaboration 01

### Phase 2: HPC Deployment (vLLM)
- Proper harmony integration
- Batch processing
- Production run
- **Status**: In progress

### Phase 3: Both Supported (if needed)
- Config flag: `BACKEND=vllm|ollama`
- Same code paths
- Backend adapter layer
- **Status**: Future consideration

## Current Status

- ✅ Ollama integration working (Elaboration 01)
- 🔄 Migrating to vLLM
- ⏸️ Waiting for vLLM deployment configuration

## Dependencies

- vLLM requires: `vllm>=0.10.1+gptoss`
- openai-harmony: `openai-harmony`
- CUDA environment on HPC

## References

- vLLM guide: [../external/vllm_guide.md](../external/vllm_guide.md)
- Harmony format: [../external/harmony_format.md](../external/harmony_format.md)
- Implementation: Elaboration 01
- Decision: CLAUDE.md Decision #TBD

## Recommendation

**Use vLLM for all HPC work**. The batching alone justifies the slightly more complex setup. Ollama can remain as a development/testing tool but is not suitable for production processing of large corpus.

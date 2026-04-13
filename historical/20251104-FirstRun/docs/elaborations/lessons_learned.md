# Lessons Learned from Elaborations

This document extracts validated patterns from successful elaborations for use in the main refactor.

## From Elaboration 01: Harmony Format Integration ✅ PASS

**Status**: Completed 2025-11-14
**Results**: [Elaborations/Elaboration01/RESULTS.md](../../Elaborations/Elaboration01/RESULTS.md)

### Pattern 1: vLLM Native Harmony Token Rendering

**Finding**: vLLM with openai_harmony library provides proper token-level harmony format support.

**Implementation**:
```python
from openai_harmony import construct_harmony_conversation, parse_harmony_response

# Construct harmony conversation with proper token rendering
prefill_ids, stop_token_ids = construct_harmony_conversation(
    system_prompt=system_prompt,
    category_prompt=category_prompt,
    document_content=document_content,
    reasoning_effort="Low",  # or "Medium", "High"
)

# Send to vLLM
from vllm import LLM, SamplingParams
from vllm.inputs import TokensPrompt

llm = LLM(model="openai/gpt-oss-20b", gpu_memory_utilization=0.85, trust_remote_code=True)
sampling_params = SamplingParams(stop_token_ids=stop_token_ids, max_tokens=512, temperature=0.0)
prompt = TokensPrompt(prompt_token_ids=prefill_ids)
outputs = llm.generate(prompts=[prompt], sampling_params=sampling_params)

# Parse response
output_tokens = outputs[0].outputs[0].token_ids
harmony_response = parse_harmony_response(output_tokens)

# Extract structured result and reasoning
result = harmony_response.get_category_result()
reasoning = harmony_response.analysis_channel
```

**Tradeoffs**:
- Requires vLLM (not Ollama)
- Slightly more complex setup than text-based prompts
- Benefits: Proper token control, reasoning transparency, variable reasoning effort

**Action**: Use this pattern for all production inference. Ollama retained only for local development/testing.

---

### Pattern 2: Reasoning Effort Control

**Finding**: Harmony format supports variable reasoning effort (Low/Medium/High) with measurable output differences.

**Results from E01**:
- Low: 104-249 tokens (mean: 153)
- Medium: 173-377 tokens (mean: 263)
- High: 364-518 tokens (mean: 448)

**Tradeoff**: 3x token cost (Low→High), ~70% longer reasoning traces provide better accuracy for complex categories.

**Action**:
- Use "Low" for simple categories (e.g., imperative verbs - clear linguistic patterns)
- Use "Medium" for most categories (balanced cost/quality)
- Use "High" for ambiguous categories requiring deep reasoning (e.g., implicit persuasion)

**Configuration**: Make `REASONING_EFFORT` configurable per category in YAML prompts.

---

### Pattern 3: Pydantic Schema Validation

**Finding**: All 9 E01 tests passed with valid JSON matching CategoryResult schema.

**Implementation**:
```python
from pydantic import BaseModel

class CategoryResult(BaseModel):
    match: Literal["yes", "maybe", "no"]
    blockquotes: list[str]

# Parse from harmony final channel
result = harmony_response.get_category_result()  # Returns CategoryResult instance
assert result.match in ["yes", "maybe", "no"]
assert isinstance(result.blockquotes, list)
```

**Finding**: Models reliably produce valid JSON when prompted via harmony final channel.

**Action**: Use Pydantic for all output validation. No need for fuzzy parsing or error recovery.

---

### Pattern 4: Store Reasoning Traces

**Finding**: Analysis channel provides valuable debugging information (50-500 chars depending on effort).

**Implementation**: Add `reasoning_trace TEXT` column to `result_category` table.

**Use cases**:
- Debug misclassifications (why did model say "yes"?)
- Improve prompts based on reasoning patterns
- Audit trail for research transparency

**Action**: Store `harmony_response.analysis_channel` in database alongside structured result.

---

## From Elaboration 02: Multi-Model Compatibility ✅ PASS

**Status**: Completed 2025-11-14
**Results**: [Elaborations/Elaboration02/RESULTS.md](../../Elaborations/Elaboration02/RESULTS.md)

### Pattern 5: Unified Model Interface

**Finding**: Both `openai/gpt-oss-20b` and `openai/gpt-oss-safeguard-20b` work identically with the same code. No model-specific handling required.

**Implementation**:
```python
# Single code path works for all gpt-oss models
GPT_MODEL = "openai/gpt-oss-20b"  # or "openai/gpt-oss-120b", "openai/gpt-oss-safeguard-20b"

llm = LLM(model=GPT_MODEL, gpu_memory_utilization=0.85, trust_remote_code=True)

# Same construct_harmony_conversation() works for all models
prefill_ids, stop_token_ids = construct_harmony_conversation(...)

# Same parse_harmony_response() works for all models
harmony_response = parse_harmony_response(output_tokens)
```

**Test Results**: 10/10 tests passed (5 tests × 2 models), 100% pass rate.

**Tradeoffs**:
- Safeguard model produces slightly longer reasoning traces (+16%, 580 vs 498 chars)
- This is expected behaviour (optimised for policy reasoning)
- No impact on structural compatibility

**Action**: Model selection purely via configuration string. No conditional logic in processing code.

---

### Pattern 6: Model Selection Strategy

**Finding**: All three models have identical API but different use cases.

**Decision matrix**:
- `openai/gpt-oss-20b`: Testing/development (faster iteration, ~18GB VRAM)
- `openai/gpt-oss-120b`: Production quality (best accuracy, requires 80GB H100)
- `openai/gpt-oss-safeguard-20b`: Policy reasoning (same speed as 20b, longer reasoning)

**Implementation**: Single `GPT_MODEL` environment variable switches models without code changes.

**Action**:
- Local testing: Use 20b
- HPC production: Use 120b
- Policy-heavy categories: Test with safeguard-20b

---

### Pattern 7: Sequential Model Loading for Tests

**Finding**: E02 used function-scoped pytest fixture with sequential model loading to avoid GPU memory conflicts.

**Implementation**:
```python
@pytest.fixture
def vllm_model_factory():
    """Factory fixture for sequential model loading."""
    from vllm import LLM
    active_models = []

    def _create_model(model_name: str):
        llm = LLM(model=model_name, gpu_memory_utilization=0.85, trust_remote_code=True)
        active_models.append(llm)
        return llm

    yield _create_model

    # Cleanup
    for llm in active_models:
        del llm
    import torch
    torch.cuda.empty_cache()
```

**Tradeoff**: Sequential loading (3 minutes for 10 tests) vs parallel loading (GPU OOM).

**Action**: Use this pattern for multi-model testing. Production uses single model instance.

---

## From Elaboration 03: SQLite Thread Safety ⏭️ SKIPPED

**Status**: SKIPPED 2025-11-14
**Reason**: vLLM native batching eliminates threading need
**See**: [Elaborations/Elaboration03/README.md](../../Elaborations/Elaboration03/README.md)

### Pattern 8: Sequential File Processing with vLLM Batching

**Decision**: Process files sequentially, batch all 15 categories per file in single vLLM call.

**Architecture**:
```python
# Pseudo-code
for file in files:
    # Batch all 15 categories
    prefill_batch = []
    for category in categories:
        prefill_ids, stop_ids = construct_harmony_conversation(...)
        prefill_batch.append(TokensPrompt(prompt_token_ids=prefill_ids))

    # Single vLLM call processes all 15 prompts simultaneously
    outputs = llm.generate(prompts=prefill_batch, sampling_params=params)

    # Parse all responses
    results = [parse_harmony_response(out.outputs[0].token_ids) for out in outputs]

    # Atomic commit: all 15 categories or none
    with db.transaction():
        for result in results:
            db.insert_result(result)
```

**Benefits**:
- No threading complexity
- No multi-connection SQLite concerns
- Simple single-connection pattern
- Per-file ACID guarantees

**Action**: Use this pattern for main refactor. No ThreadPoolExecutor needed.

---

## From Elaboration 04: Batch Processing Performance 🔄 TODO

**Status**: TODO
**See**: [Elaborations/Elaboration04/README.md](../../Elaborations/Elaboration04/README.md)

Expected patterns to validate:
- Optimal batch size for vLLM (hypothesis: batch_size=15)
- Speedup factor vs sequential processing
- GPU utilization metrics
- Memory requirements per batch size

---

## From Elaboration 05: HPC vLLM Startup 🔄 TODO

**Status**: TODO

Expected patterns to validate:
- vLLM startup sequence on H100
- Model caching strategy (HuggingFace cache location)
- Tensor parallelism configuration (TP=2 for H100)
- Acceptable startup times

---

## Summary of Validated Patterns (E01 + E02)

### Core Implementation Patterns
1. ✅ **vLLM + openai_harmony** - Use `construct_harmony_conversation()` and `parse_harmony_response()`
2. ✅ **Variable reasoning effort** - Configure Low/Medium/High per category
3. ✅ **Pydantic validation** - All models produce valid CategoryResult JSON
4. ✅ **Store reasoning traces** - Add `reasoning_trace TEXT` column
5. ✅ **Unified model interface** - Single code path for all gpt-oss models
6. ✅ **Model selection strategy** - Switch via configuration string only
7. ✅ **Sequential file processing** - Batch all 15 categories per file in single vLLM call
8. ✅ **No threading needed** - vLLM native batching eliminates Python threading

### Architectural Decisions Validated
- ✅ vLLM is correct backend choice (proper harmony support)
- ✅ Multi-model support requires zero conditional logic
- ✅ Sequential file + vLLM batch processing is optimal architecture
- ✅ Reasoning transparency is achievable and valuable

### Pending Validation (E04 + E05)
- 🔄 Optimal batch size and speedup measurements
- 🔄 HPC deployment pattern and startup times

---

## Cross-References

- **Implementation examples**: Individual elaboration RESULTS.md files
  - [E01 Results](../../Elaborations/Elaboration01/RESULTS.md)
  - [E02 Results](../../Elaborations/Elaboration02/RESULTS.md)
- **Architecture docs**: [../architecture/](../architecture/)
- **Decision rationale**: [../../CLAUDE.md](../../CLAUDE.md)
- **Elaboration plan**: [../../ELABORATION_PLAN.md](../../ELABORATION_PLAN.md)

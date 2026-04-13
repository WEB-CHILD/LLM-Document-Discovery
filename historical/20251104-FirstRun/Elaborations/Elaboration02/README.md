# Elaboration 02: Multi-Model Compatibility (vLLM)

## Hypothesis to Falsify

**"The same harmony token rendering works identically across openai/gpt-oss-20b and openai/gpt-oss-safeguard-20b with no model-specific code paths required."**

## Scope

**Local testing**: gpt-oss-20b and gpt-oss-safeguard-20b (local GPU memory constraints)
**HPC validation**: gpt-oss-120b compatibility verified by running full E01 test suite on HPC with 120b model

## What We're Testing

1. Can we send the same harmony token sequences to both 20b and safeguard-20b models via vLLM?
2. Do both models return responses in the same structure?
3. Does the gpt-oss-safeguard model require special handling (different prompt format, different parsing)?
4. Can we use a single `parse_harmony_response()` function for both models?
5. Are the quality/accuracy differences acceptable (we expect differences, but structure should be identical)?

## Why This Matters

The refactor assumes we can switch models via configuration without code changes. If each model requires different:
- Token rendering (harmony format variations)
- Response parsing (different channel structures)
- Schema validation (model-specific outputs)

Then we need conditional logic throughout the codebase, increasing complexity and maintenance burden.

## Success Criteria

### ✅ PASS
- Same `construct_harmony_conversation()` function works for both 20b and safeguard-20b
- Same `parse_harmony_response()` function works for both models
- Both models return valid JSON matching CategoryResult schema
- Both models provide reasoning traces via analysis channel
- No model-specific error handling needed
- **120b compatibility assumed via HPC test** (run E01 suite with 120b model)

### ⚠️  PARTIAL
- Safeguard model requires minor adjustments to prompt template
- Fallback: Add minimal conditional logic for safeguard model only

### ❌ FAIL
- Models require completely different handling
- OR: Safeguard model consistently fails to produce valid output
- OR: Response structures are incompatible between models

## Test Approach

### Phase 1: Write Failing Tests (pytest)
Create `test_multi_model_compatibility.py` with tests that:
1. Attempt to send same token sequence to both 20b and safeguard-20b via vLLM
2. Expect identical response structure from harmony parsing
3. **These tests will FAIL if safeguard model isn't available or has incompatibilities**

### Phase 2: Confirm Test Can Falsify
Run pytest and verify it fails with clear errors about:
- Missing safeguard model (need to load it)
- Incompatible response formats
- Schema validation failures

### Phase 3: Load Required Models
```python
# Load models via vLLM (downloads from HuggingFace automatically)
llm_20b = LLM(model="openai/gpt-oss-20b", trust_remote_code=True)
llm_safeguard = LLM(model="openai/gpt-oss-safeguard-20b", trust_remote_code=True)
# Note: 120b testing happens on HPC by running E01 suite with MODEL=120b
```

### Phase 4: Implement Compatibility Layer (if needed)
If tests reveal incompatibilities, implement minimal adapter logic

### Phase 5: Verify Tests Pass
Re-run pytest to confirm both models work with same code

## Files

- `README.md` - This file
- `test_multi_model_compatibility.py` - Pytest tests (write first, expect failures)
- `model_adapter.py` - Compatibility layer if needed (create only if tests show it's necessary)
- `RESULTS.md` - Findings and recommendations

## Expected Outcome

Either:
1. **PASS**: Both models work identically, no adapter needed (120b validated on HPC)
2. **PARTIAL**: Safeguard needs minor tweaks, create minimal adapter
3. **FAIL**: Fundamental incompatibility - need to reconsider multi-model support

## Dependencies

- Elaboration 01 must PASS first (we need working harmony integration with vLLM)
- Requires loading openai/gpt-oss-safeguard-20b (~13GB weights)
- Sufficient GPU memory for both 20b models (or sequential testing with model unloading)
- vLLM 0.10.2 with openai_harmony 0.0.8
- **120b testing**: HPC environment with sufficient GPU memory (80GB H100)

## Key Differences from Ollama Version

- Models loaded via vLLM's `LLM()` class instead of Ollama pull
- Testing proper harmony token compatibility, not text-based markers
- Can test models sequentially or use model unloading to manage GPU memory
- Focus on native harmony channel structure consistency across models

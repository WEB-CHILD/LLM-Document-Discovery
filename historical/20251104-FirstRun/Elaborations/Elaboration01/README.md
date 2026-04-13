# Elaboration 01: Harmony Format Integration (vLLM)

## Hypothesis to Falsify

**"The openai_harmony library can properly render harmony tokens for vLLM, and vLLM can generate structured output with separate reasoning and result channels."**

## What We're Testing

1. Can we construct harmony-format token sequences using the openai_harmony library?
2. Does vLLM (running openai/gpt-oss-20b) accept and process harmony token IDs?
3. Does the response contain distinct `analysis` and `final` channels as documented?
4. Can we extract the reasoning trace from the `analysis` channel?
5. Can we parse the structured JSON from the `final` channel and validate it against our Pydantic schema?

## Why This Matters

The entire refactor depends on using the harmony response format to:
- Capture reasoning traces for debugging
- Get structured JSON outputs
- Support multiple models (20b, 120b, safeguard) with the same code
- Leverage vLLM's native batching for 4x performance improvement

If harmony doesn't work with vLLM, we need to either:
- Find an alternative approach (text-based markers)
- Use a different model backend (transformers directly)
- Abandon reasoning trace capture

## Success Criteria

### ✅ PASS
- vLLM accepts harmony token IDs without errors
- Response contains native harmony channel structure (analysis + final)
- Response parsing via openai_harmony extracts both channels correctly
- JSON validates against CategoryResult Pydantic schema
- Reasoning trace is extractable and readable

### ⚠️  PARTIAL
- vLLM accepts tokens and returns valid JSON
- BUT: Channel parsing fails or channels are malformed
- Fallback: We can still extract JSON but lose structured reasoning

### ❌ FAIL
- vLLM rejects the token sequence
- OR: Response is unparseable
- OR: JSON doesn't match schema
- OR: Complete failure to communicate

## Test Approach

### Phase 1: Write Failing Test (pytest)
Create `test_harmony_integration.py` with pytest that:
1. Attempts to use openai_harmony to render token sequences
2. Sends to vLLM via LLM.generate()
3. Expects to parse harmony channels from output tokens
4. **This test will likely FAIL initially** - proving we can detect the problem

### Phase 2: Confirm Test Can Falsify
Run pytest and verify it fails with clear error message about missing channels or parsing failures

### Phase 3: Implement Solution
Once test failure is confirmed, implement the actual harmony integration

### Phase 4: Verify Test Passes
Re-run pytest to confirm our implementation works

## Files

- `README.md` - This file
- `test_harmony_integration.py` - Pytest test (9 tests covering full workflow)
- `harmony_integration.py` - Implementation (vLLM + openai_harmony integration)
- `conftest.py` - Session-scoped vLLM model fixture
- `RESULTS.md` - Complete findings and recommendations

## Actual Outcome

**✅ PASS** - All 9 tests pass

Harmony format works perfectly with vLLM:
1. **Token Rendering**: openai_harmony correctly renders harmony token sequences
2. **vLLM Generation**: Accepts TokensPrompt format, generates valid responses
3. **Channel Parsing**: Both analysis and final channels extracted correctly
4. **JSON Validation**: CategoryResult schema validates successfully
5. **Performance**: 163 tok/s output, deterministic with temperature=0.0

### Key Findings

- **vLLM 0.10.2 API**: Uses `prompts` parameter with `TokensPrompt` TypedDict
- **Reasoning Effort**: Must be capitalized ("Low", "Medium", "High")
- **Content Format**: Message content is list of dicts, extract text from items
- **Prompt Construction**: Use simple examples, not full Pydantic schemas
- **Session-Scoped Fixture**: Saves 10-30s per test by loading model once

See [RESULTS.md](RESULTS.md) for complete documentation and extracted patterns.

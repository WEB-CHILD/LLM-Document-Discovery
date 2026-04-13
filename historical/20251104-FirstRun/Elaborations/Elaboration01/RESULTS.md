# Elaboration 01 Results: Harmony Format Integration (vLLM)

**Date**: 2025-11-14
**Status**: ✅ PASS (vLLM version)

## Hypothesis

"The openai_harmony library can properly render harmony tokens for vLLM, and vLLM can generate structured output with separate reasoning and result channels."

## Test Results

| Test | Result | Notes |
|------|--------|-------|
| 1. openai_harmony import | ✅ PASS | Library loads successfully |
| 2. vLLM import | ✅ PASS | vLLM 0.10.2 available |
| 3. Load test data | ✅ PASS | Prompts and documents load correctly |
| 4. Construct harmony conversation | ✅ PASS | Token rendering produces valid token sequences |
| 5. vLLM model loaded | ✅ PASS | Session-scoped fixture avoids reload penalty |
| 6. vLLM generate | ✅ PASS | LLM.generate() works with TokensPrompt format |
| 7. Analysis channel present | ✅ PASS | Reasoning trace extracted from output tokens |
| 8. Valid JSON output | ✅ PASS | CategoryResult schema validates |
| 9. Full integration | ✅ PASS | End-to-end workflow with real document |

**Total**: 9/9 tests passed

## Key Findings

### 1. vLLM 0.10.2 API Differences

**Finding**: vLLM 0.10.2 API differs from documentation (which shows 0.11.0):

- **Parameter**: `prompts` (not `prompt_token_ids`)
- **Format**: Requires `TokensPrompt` TypedDict:
  ```python
  from vllm.inputs import TokensPrompt
  prompt = TokensPrompt(prompt_token_ids=prefill_ids)
  outputs = llm.generate(prompts=[prompt], sampling_params=params)
  ```

**Impact**: Documentation examples for vLLM 0.11.0 don't work on 0.10.2. Need to use `inspect.signature()` to discover actual API.

### 2. openai_harmony Message Content Format

**Finding**: Message content from `parse_messages_from_completion_tokens()` is a list of content items, not a string:

```python
msg_dict["content"] = [
    {"type": "text", "text": "actual content here"}
]
```

**Solution**: Extract text from content list:
```python
if isinstance(content, list):
    text = "".join(item.get("text", "") for item in content if item.get("type") == "text")
```

### 3. Reasoning Effort Parameter Capitalization

**Finding**: openai_harmony expects capitalized enum values:
- ❌ "low", "medium", "high"
- ✅ "Low", "Medium", "High"

**Error if wrong**: `ValueError: invalid conversation JSON: unknown variant 'medium', expected one of 'Low', 'Medium', 'High'`

### 4. Prompt Construction for gpt-oss Models

**Finding**: Including full Pydantic JSON schema in prompt causes model to output the schema itself instead of results.

**Solution**: Use simple format example instead:
```python
# ❌ Don't include full schema
schema = CategoryResult.model_json_schema()
prompt = f"Output JSON matching schema: {json.dumps(schema)}"

# ✅ Use format example
prompt = """Output ONLY valid JSON with this structure:
{
  "match": "yes" or "maybe" or "no",
  "blockquotes": ["quote 1", "quote 2"]
}"""
```

### 5. Session-Scoped vLLM Fixture

**Finding**: Loading vLLM model takes 10-30 seconds. Session-scoped pytest fixture avoids reload penalty:

```python
@pytest.fixture(scope="session")
def vllm_model():
    from vllm import LLM
    llm = LLM(
        model="openai/gpt-oss-20b",
        gpu_memory_utilization=0.85,
        trust_remote_code=True,
    )
    return llm
```

**Impact**: Tests run in ~32 seconds total instead of 10-30 seconds per test.

### 6. Model Behavior

The gpt-oss:20b model with proper harmony token rendering:
- ✅ Outputs reasoning in analysis channel
- ✅ Outputs valid JSON in final channel
- ✅ Follows temperature=0.0 (deterministic)
- ✅ Respects stop tokens
- ✅ Extracts blockquotes correctly

**Example response structure** (parsed from tokens):
```
Analysis channel:
"We need to extract sentences containing imperative verbs. The document is a web page from 1996..."

Final channel:
{
  "match": "yes",
  "blockquotes": ["To browse the InterNIC Directory of Directories, select a category..."]
}
```

### 7. Performance Metrics

From test run with 1000-char document:
- **Input tokens**: ~700
- **Output tokens**: ~615
- **Analysis channel**: 2632 characters
- **Final channel**: 168 characters
- **Generation time**: ~5.8 seconds
- **Throughput**: 119 tok/s input, 163 tok/s output
- **Finish reason**: "stop" (completed naturally)

## Extracted Pattern

### For Refactor Use

The working implementation in `harmony_integration.py` provides:

```python
def construct_harmony_conversation(
    system_prompt: str,
    category_prompt: str,
    document_content: str,
    reasoning_effort: str = "Medium"  # Must be capitalized
) -> tuple[List[int], List[int]]:
    """
    Construct harmony conversation using openai_harmony token rendering.

    Returns:
        (prefill_ids, stop_token_ids) for vLLM generation
    """
    encoding = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS)

    # Use builder pattern for content construction
    system_content = SystemContent.new().with_reasoning_effort(reasoning_effort)

    # Simple format example, not full JSON schema
    developer_instructions = f"""{system_prompt}
# Category Instructions
{category_prompt}
# Document to Analyze
{document_content}
# Response Format
Use the analysis channel for your reasoning trace.
In the final channel, provide ONLY valid JSON with this structure:
{{
  "match": "yes" or "maybe" or "no",
  "blockquotes": ["quote 1", "quote 2"]
}}"""

    developer_content = DeveloperContent.new().with_instructions(developer_instructions)

    conversation = Conversation.from_messages([
        Message.from_role_and_content(Role.SYSTEM, system_content),
        Message.from_role_and_content(Role.DEVELOPER, developer_content),
    ])

    prefill_ids = encoding.render_conversation_for_completion(conversation, Role.ASSISTANT)
    stop_token_ids = encoding.stop_tokens_for_assistant_actions()

    return prefill_ids, stop_token_ids

def parse_harmony_response(output_tokens: List[int]) -> HarmonyResponse:
    """
    Parse vLLM output tokens to extract channels.

    Returns:
        HarmonyResponse with analysis_channel and final_channel strings
    """
    encoding = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS)
    messages = encoding.parse_messages_from_completion_tokens(
        output_tokens,
        Role.ASSISTANT
    )

    analysis = ""
    final = ""

    for message in messages:
        msg_dict = message.to_dict()

        if msg_dict.get("channel") == "analysis":
            content = msg_dict.get("content", [])
            if isinstance(content, list):
                analysis = "".join(item.get("text", "") for item in content if item.get("type") == "text")

        elif msg_dict.get("channel") == "final":
            content = msg_dict.get("content", [])
            if isinstance(content, list):
                final = "".join(item.get("text", "") for item in content if item.get("type") == "text")

    return HarmonyResponse(analysis_channel=analysis, final_channel=final)
```

## vLLM Integration Pattern

```python
from vllm import LLM, SamplingParams
from vllm.inputs import TokensPrompt

# Initialize (session-scoped for tests)
llm = LLM(
    model="openai/gpt-oss-20b",
    gpu_memory_utilization=0.85,
    trust_remote_code=True,
)

# Construct harmony conversation
prefill_ids, stop_token_ids = construct_harmony_conversation(
    system_prompt, category_prompt, document_content, "Medium"
)

# Create sampling params
sampling_params = SamplingParams(
    max_tokens=1024,
    temperature=0.0,
    stop_token_ids=stop_token_ids,
)

# Generate with TokensPrompt format (vLLM 0.10.2 API)
prompt = TokensPrompt(prompt_token_ids=prefill_ids)
outputs = llm.generate(prompts=[prompt], sampling_params=sampling_params)

# Parse response
output_tokens = outputs[0].outputs[0].token_ids
harmony_response = parse_harmony_response(output_tokens)

# Extract result
result = harmony_response.get_category_result()
```

## Decision Points

### ✅ vLLM with openai_harmony is viable

- Native harmony token rendering works correctly
- Proper channel separation (analysis + final)
- Deterministic with temperature=0.0
- Good performance (163 tok/s output)

### ✅ Session-scoped fixture pattern

- Avoid 10-30 second model load penalty
- Reuse loaded model across all tests
- Keep GPU memory allocated

### ⚠️ Version-specific API

- vLLM 0.10.2 API differs from docs
- Use `inspect.signature()` to discover APIs
- Document actual working code, not assumptions

### ✅ Ready for production integration

- All 9 tests pass
- Pattern proven with real documents
- Proceed to main refactor

## Recommendations

1. **Use vLLM over Ollama** - Native harmony support, better batching, 4x performance improvement
2. **Session-scoped LLM instance** - Load model once, reuse across requests
3. **Batch all 15 categories per file** - vLLM native batching (see Elaboration 04)
4. **Store reasoning traces** - Add `reasoning_trace TEXT` column to database
5. **Use simple format examples** - Don't include full Pydantic schemas in prompts
6. **Capitalize reasoning effort** - "Low", "Medium", "High" (not lowercase)

## Code to Extract

Files ready for production use:
- `harmony_integration.py` (183 lines) - Reference implementation
- `conftest.py` (36 lines) - Session-scoped vLLM fixture
- `test_harmony_integration.py` (340 lines) - Full test coverage

## Known Issues

1. **Pydantic serialization warning**: `openai_harmony` expects enum for reasoning_effort but we pass string. Works but generates warnings.
2. **Multiprocessing deprecation**: vLLM uses `fork()` in multi-threaded context. Harmless but noisy.
3. **Version sensitivity**: Code is specific to vLLM 0.10.2 + openai_harmony 0.0.8. May break with updates.

## Next Steps

1. ✅ Elaboration 01 complete (vLLM version)
2. ➡️ Proceed to Elaboration 02 (Multi-model compatibility with vLLM)
3. Test same pattern with gpt-oss-120b
4. ➡️ Proceed to Elaboration 04 (Batch processing 15 categories)

# How to Run gpt-oss with vLLM

**Source**: OpenAI gpt-oss vLLM integration guide
**Retrieved**: 2025-11-14
**Purpose**: Server-grade inference engine for gpt-oss models on GPUs (H100s, etc.)

## Summary

vLLM is optimized for high-throughput inference on dedicated GPUs. It's recommended over Ollama for:
- Server applications
- HPC environments
- Multi-GPU setups
- Batch processing

## Installation

```bash
# Using uv (recommended)
uv venv --python 3.12 --seed
source .venv/bin/activate
uv pip install --pre vllm==0.10.1+gptoss \
    --extra-index-url https://wheels.vllm.ai/gpt-oss/ \
    --extra-index-url https://download.pytorch.org/whl/nightly/cu128 \
    --index-strategy unsafe-best-match
```

## Model Selection

- **openai/gpt-oss-20b**: Requires ~16GB VRAM
- **openai/gpt-oss-120b**: Requires ~60GB VRAM (single H100 or multi-GPU)

Both models are MXFP4 quantized by default.

## Quick Start: API Server

```bash
# Start server
vllm serve openai/gpt-oss-20b

# Server runs on http://localhost:8000
```

### Using the API

vLLM exposes OpenAI-compatible endpoints:

**Chat Completions**:
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="EMPTY"
)

response = client.chat.completions.create(
    model="openai/gpt-oss-20b",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Explain MXFP4 quantization."}
    ]
)

print(response.choices[0].message.content)
```

**Responses API** (native support):
```python
response = client.responses.create(
    model="openai/gpt-oss-120b",
    instructions="You are a helpful assistant.",
    input="Explain MXFP4 quantization."
)

print(response.output_text)
```

## Direct Sampling (Python Library)

For maximum control, use vLLM directly with harmony token rendering:

```python
from vllm import LLM, SamplingParams
from openai_harmony import (
    load_harmony_encoding,
    HarmonyEncodingName,
    Conversation,
    Message,
    Role,
    SystemContent,
    DeveloperContent,
)

# 1. Build conversation with harmony
encoding = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS)

convo = Conversation.from_messages([
    Message.from_role_and_content(Role.SYSTEM, SystemContent.new()),
    Message.from_role_and_content(
        Role.DEVELOPER,
        DeveloperContent.new().with_instructions("Always respond in riddles")
    ),
    Message.from_role_and_content(Role.USER, "What is the weather like in SF?"),
])

# 2. Render to tokens (prefill)
prefill_ids = encoding.render_conversation_for_completion(convo, Role.ASSISTANT)

# 3. Get stop tokens
stop_token_ids = encoding.stop_tokens_for_assistant_actions()

# 4. Initialize vLLM
llm = LLM(
    model="openai/gpt-oss-120b",
    trust_remote_code=True,
)

# 5. Configure sampling
sampling = SamplingParams(
    max_tokens=128,
    temperature=1.0,
    stop_token_ids=stop_token_ids,
)

# 6. Generate
outputs = llm.generate(
    prompt_token_ids=[prefill_ids],  # Batch of size 1
    sampling_params=sampling,
)

# 7. Parse response tokens
output_tokens = outputs[0].outputs[0].token_ids
messages = encoding.parse_messages_from_completion_tokens(
    output_tokens,
    Role.ASSISTANT
)

# 8. Extract structured messages
for message in messages:
    print(message.to_dict())
```

## Batch Processing

vLLM excels at batching:

```python
# Multiple prompts at once
prefill_batch = [
    encoding.render_conversation_for_completion(convo1, Role.ASSISTANT),
    encoding.render_conversation_for_completion(convo2, Role.ASSISTANT),
    encoding.render_conversation_for_completion(convo3, Role.ASSISTANT),
]

outputs = llm.generate(
    prompt_token_ids=prefill_batch,
    sampling_params=sampling,
)

# Process batch results
for output in outputs:
    tokens = output.outputs[0].token_ids
    messages = encoding.parse_messages_from_completion_tokens(tokens, Role.ASSISTANT)
```

## Function Calling

Works with both Chat Completions and Responses APIs:

```python
tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get current weather",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"]
        },
    },
}]

response = client.chat.completions.create(
    model="openai/gpt-oss-120b",
    messages=[{"role": "user", "content": "Weather in Berlin?"}],
    tools=tools
)
```

**Important**: Return reasoning from API back to model with tool result until final answer.

## HPC Deployment

### Custom Model Directory

```bash
vllm serve openai/gpt-oss-20b \
  --model-dir /work/.cache/vllm/models \
  --host 0.0.0.0 \
  --port 8000
```

### GPU Configuration

```bash
# Check GPUs
nvidia-smi

# vLLM auto-detects and uses available GPUs
# For 120b model, it will distribute across multiple GPUs if needed
```

### Environment Variables

```bash
export VLLM_CACHE_DIR=/work/.cache/vllm
export CUDA_VISIBLE_DEVICES=0,1,2,3  # Select specific GPUs
```

## Performance Considerations

### vs Ollama
- **vLLM**: Better for servers, batch processing, multi-GPU
- **Ollama**: Better for consumer hardware, local dev, single user

### Batching Benefits
- Process multiple prompts simultaneously
- Better GPU utilization
- Higher throughput

### Memory Management
- vLLM uses PagedAttention for efficient KV cache
- Can handle larger batches than naive implementations
- Automatically distributes across GPUs for 120b model

## Agents SDK Integration

```python
import asyncio
from openai import AsyncOpenAI
from agents import Agent, Runner, OpenAIResponsesModel

agent = Agent(
    name="Assistant",
    instructions="You only respond in haikus.",
    model=OpenAIResponsesModel(
        model="openai/gpt-oss-120b",
        openai_client=AsyncOpenAI(
            base_url="http://localhost:8000/v1",
            api_key="EMPTY",
        ),
    ),
)

result = await Runner.run(agent, "What's the weather in Tokyo?")
```

## Common Patterns

### Startup Script
```bash
#!/bin/bash
# Start vLLM server in background
vllm serve openai/gpt-oss-20b \
  --model-dir /work/.cache/vllm/models \
  --host 0.0.0.0 &

VLLM_PID=$!

# Wait for server
sleep 10

# Test endpoint
curl http://localhost:8000/v1/models

# Run processing
python main.py

# Cleanup
kill $VLLM_PID
```

### Testing Generation
```python
def test_vllm_generation():
    llm = LLM(model="openai/gpt-oss-20b", trust_remote_code=True)
    encoding = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS)

    # Build conversation
    convo = Conversation.from_messages([...])
    prefill = encoding.render_conversation_for_completion(convo, Role.ASSISTANT)

    # Generate
    outputs = llm.generate(
        prompt_token_ids=[prefill],
        sampling_params=SamplingParams(max_tokens=100, temperature=0.0)
    )

    # Parse
    tokens = outputs[0].outputs[0].token_ids
    messages = encoding.parse_messages_from_completion_tokens(tokens, Role.ASSISTANT)

    return messages
```

## Cross-References

- Harmony format: [harmony_format.md](harmony_format.md)
- Python API: [harmony_python_api.md](harmony_python_api.md)
- Architecture decision: [vllm_vs_ollama.md](../architecture/vllm_vs_ollama.md)
- Implementation: Elaboration 01
- Decision: CLAUDE.md Decision #TBD

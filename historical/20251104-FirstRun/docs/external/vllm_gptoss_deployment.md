# vLLM gpt-oss Deployment Guide for H100

**Source**: vLLM Recipes - GPT OSS
**Retrieved**: 2025-11-14
**Purpose**: Production deployment guide for gpt-oss on NVIDIA H100 GPUs

## Quick Start (H100/H200)

### Installation

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install vllm==0.10.2 --torch-backend=auto

# Or use official docker
docker run --gpus all \
    -p 8000:8000 \
    --ipc=host \
    vllm/vllm-openai:v0.10.2 \
    --model openai/gpt-oss-20b
```

### Launch Server (H100)

**Recommended**: TP=2 for best performance tradeoff on H100

```bash
# 20b - single GPU
vllm serve openai/gpt-oss-20b --async-scheduling

# 120b - best performance with TP=2
vllm serve openai/gpt-oss-120b --tensor-parallel-size 2 --async-scheduling

# Alternative TP configurations
vllm serve openai/gpt-oss-120b --async-scheduling  # TP=1
vllm serve openai/gpt-oss-120b --tensor-parallel-size 4 --async-scheduling  # TP=4
```

**Key flags**:
- `--async-scheduling`: Higher performance (not compatible with structured output)
- FlashAttention3 backend used automatically on Hopper
- Marlin MXFP4 MoE enabled by default

## Configuration for Production

### Recommended Config (H100)

Create `GPT-OSS_Hopper.yaml`:

```yaml
compilation-config: '{"cudagraph_mode":"PIECEWISE"}'
async-scheduling: true
no-enable-prefix-caching: true
cuda-graph-sizes: 2048
max-num-batched-tokens: 8192
max-model-len: 10240
```

### Launch with Config

```bash
vllm serve openai/gpt-oss-120b \
  --config GPT-OSS_Hopper.yaml \
  --tensor-parallel-size 2 \
  --max-num-seqs 512
```

## Key Parameters

### Fixed (Don't Change)
- `compilation-config`: CUDA graph mode for performance
- `async-scheduling`: Reduces host overheads between steps
- `no-enable-prefix-caching`: For consistent performance measurement
- `cuda-graph-sizes: 2048`: Max size for CUDA graphs

### Tunable (Adjust for Your Needs)

**`tensor-parallel-size`** (TP):
- `TP=1`: Best throughput per GPU
- `TP=2`: **Recommended for H100** - balanced performance
- `TP=4` or `TP=8`: Better per-user latency, lower per-GPU throughput

**`max-num-seqs`** (Batch Size):
- `512`: High throughput
- `128`: Balanced
- `16`: Low latency
- Must match client `--max-concurrency`

**`max-num-batched-tokens`**:
- `8192`: Recommended default
- `16384`: Slightly higher throughput, less even TPOT distribution

**`max-model-len`**:
- Total tokens (input + output) per request
- Must be >= expected max input + max output
- Example: 1024 input + 1024 output = 2048 minimum

## Performance Tuning Scenarios

### Maximum Throughput
```bash
vllm serve openai/gpt-oss-120b \
  --tensor-parallel-size 1 \
  --max-num-seqs 512 \
  --max-num-batched-tokens 8192 \
  --gpu-memory-utilization 0.95
```

### Minimum Latency
```bash
vllm serve openai/gpt-oss-120b \
  --tensor-parallel-size 4 \
  --max-num-seqs 8 \
  --max-num-batched-tokens 8192
```

### Balanced (Recommended)
```bash
vllm serve openai/gpt-oss-120b \
  --tensor-parallel-size 2 \
  --max-num-seqs 128 \
  --max-num-batched-tokens 8192
```

## Direct Sampling (Python Library)

For maximum control with harmony tokens:

```python
from vllm import LLM, SamplingParams
from openai_harmony import (
    load_harmony_encoding,
    HarmonyEncodingName,
    Conversation,
    Message,
    Role,
    SystemContent,
)

# 1. Initialize vLLM
llm = LLM(
    model="openai/gpt-oss-120b",
    trust_remote_code=True,
    tensor_parallel_size=2,
)

# 2. Build conversation
encoding = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS)
convo = Conversation.from_messages([
    Message.from_role_and_content(Role.SYSTEM, SystemContent.new()),
    Message.from_role_and_content(Role.USER, "Your question here")
])

# 3. Render to tokens
prefill_ids = encoding.render_conversation_for_completion(convo, Role.ASSISTANT)
stop_token_ids = encoding.stop_tokens_for_assistant_actions()

# 4. Generate
sampling = SamplingParams(
    max_tokens=128,
    temperature=0.0,
    stop_token_ids=stop_token_ids,
)

outputs = llm.generate(
    prompt_token_ids=[prefill_ids],
    sampling_params=sampling,
)

# 5. Parse response
output_tokens = outputs[0].outputs[0].token_ids
messages = encoding.parse_messages_from_completion_tokens(
    output_tokens,
    Role.ASSISTANT
)
```

## Batch Processing

vLLM excels at batching multiple prompts:

```python
# Render multiple conversations
prefill_batch = [
    encoding.render_conversation_for_completion(convo1, Role.ASSISTANT),
    encoding.render_conversation_for_completion(convo2, Role.ASSISTANT),
    encoding.render_conversation_for_completion(convo3, Role.ASSISTANT),
    # ... up to max_num_seqs
]

# Generate all at once
outputs = llm.generate(
    prompt_token_ids=prefill_batch,
    sampling_params=sampling,
)

# Process batch results
for output in outputs:
    tokens = output.outputs[0].token_ids
    messages = encoding.parse_messages_from_completion_tokens(tokens, Role.ASSISTANT)
```

## HPC-Specific Setup

### Environment Variables

```bash
# Cache directory
export VLLM_CACHE_DIR=/work/.cache/vllm
export HF_HOME=/work/.cache/huggingface

# GPU selection (if needed)
export CUDA_VISIBLE_DEVICES=0,1,2,3
```

### Custom Model Directory

```bash
vllm serve openai/gpt-oss-20b \
  --model-dir /work/.cache/vllm/models \
  --host 0.0.0.0 \
  --port 8000
```

### Startup Script Template

```bash
#!/bin/bash

# Set cache paths
export VLLM_CACHE_DIR=/work/.cache/vllm
export HF_HOME=/work/.cache/huggingface

# Start vLLM in background
vllm serve openai/gpt-oss-20b \
  --config GPT-OSS_Hopper.yaml \
  --tensor-parallel-size 2 \
  --max-num-seqs 128 \
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

## Performance Metrics

### Key Metrics
- **TTFT** (Time to First Token): Latency to first output token
- **TPOT** (Time Per Output Token): Time between tokens after first
- **ITL** (Inter-Token Latency): Delay between token completions
- **E2EL** (End-to-End Latency): Total request time
- **Output token throughput**: Generated tokens/second
- **Total token throughput**: (Input + output) tokens/second

### Benchmarking

```bash
vllm bench serve \
  --host 0.0.0.0 \
  --port 8000 \
  --model openai/gpt-oss-120b \
  --trust-remote-code \
  --dataset-name random \
  --random-input-len 1024 \
  --random-output-len 1024 \
  --ignore-eos \
  --max-concurrency 128 \
  --num-prompts 640 \
  --save-result --result-filename benchmark_results.json
```

## Known Limitations

### H100-Specific Issues

**TP=1 Memory Issue**:
```bash
# If OOM with TP=1, increase GPU memory utilization or reduce batch tokens
vllm serve openai/gpt-oss-120b \
  --gpu-memory-utilization 0.95 \
  --max-num-batched-tokens 1024
```

**TP=2 Memory**:
```bash
# Keep GPU memory utilization < 0.95 for TP=2
vllm serve openai/gpt-oss-120b \
  --tensor-parallel-size 2 \
  --gpu-memory-utilization 0.85
```

### General Limitations
- Responses API has several WIP features (streaming, annotations, etc.)
- Usage accounting currently returns zeros
- Function calling only supports `tool_choice="auto"`

## Harmony Format Support

| Feature | Chat Completions | Responses API |
|---------|-----------------|---------------|
| Basic text generation | ✅ | ✅ |
| Structured output | ✅ | ✅ |
| Streaming | ✅ | ✅ (partial) |
| Function calling | ✅ | ✅ |

## Troubleshooting

### Triton Error
If you see `tl.language not defined`:
```bash
# Remove other triton installations
pip uninstall pytorch-triton triton
```

### tiktoken Error
```bash
# Download encodings in advance
mkdir -p tiktoken_encodings
wget -O tiktoken_encodings/o200k_base.tiktoken \
  "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"
wget -O tiktoken_encodings/cl100k_base.tiktoken \
  "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
export TIKTOKEN_ENCODINGS_BASE=${PWD}/tiktoken_encodings
```

## For Our Use Case (7,466 files × 15 categories)

**Recommended Configuration**:
```bash
vllm serve openai/gpt-oss-20b \
  --config GPT-OSS_Hopper.yaml \
  --tensor-parallel-size 2 \
  --max-num-seqs 15 \
  --max-num-batched-tokens 8192 \
  --max-model-len 16384 \
  --gpu-memory-utilization 0.85
```

**Rationale**:
- Batch all 15 categories per file together
- TP=2 for balanced throughput/latency
- max-model-len supports 1000-char docs + reasoning + output

## Cross-References

- Architecture: [vllm_vs_ollama.md](../architecture/vllm_vs_ollama.md)
- Harmony API: [harmony_python_api.md](harmony_python_api.md)
- General vLLM guide: [vllm_guide.md](vllm_guide.md)
- Implementation: Elaboration 01 (vLLM version)

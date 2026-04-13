# OpenAI Harmony Response Format

**Source**: https://cookbook.openai.com/guides/harmony-response-format
**Retrieved**: 2025-11-14
**Purpose**: Specification for gpt-oss model conversation structure and reasoning format

## Summary

Harmony is the structured prompt format that gpt-oss models were trained on. It defines:
- Message roles (system, developer, user, assistant, tool)
- Channels for separating reasoning (analysis) from output (final)
- Special tokens for structure (`<|start|>`, `<|end|>`, `<|channel|>`, etc.)
- Reasoning effort levels (low, medium, high)

## Key Concepts

### Roles
- `system` - Model identity, reasoning effort, meta information
- `developer` - Instructions and tool definitions ("system prompt" in other formats)
- `user` - User input
- `assistant` - Model output (can span multiple messages)
- `tool` - Tool execution results

**Hierarchy**: system > developer > user > assistant > tool

### Channels
Assistant messages use channels to separate types of content:
- `analysis` - Chain of thought reasoning (NOT shown to users, may contain unsafe content)
- `commentary` - Tool calls and user-facing preambles
- `final` - User-facing responses

**Important**: Analysis channel is not safety-tuned. Never show to end users.

### Message Format
```
<|start|>{role}<|channel|>{channel}<|message|>{content}<|end|>
```

Stop tokens:
- `<|return|>` - Model is done (replace with `<|end|>` in history)
- `<|call|>` - Tool call requested

### System Message Template
```
<|start|>system<|message|>You are ChatGPT, a large language model trained by OpenAI.
Knowledge cutoff: 2024-06
Current date: 2025-06-28
Reasoning: {low|medium|high}
# Valid channels: analysis, commentary, final. Channel must be included for every message.<|end|>
```

### Developer Message Template
```
<|start|>developer<|message|># Instructions
{your instructions}

# Tools
{optional tool definitions}<|end|>
```

### Example Response
```
<|channel|>analysis<|message|>User asks: "What is 2 + 2?" Simple arithmetic. Provide answer.<|end|>
<|start|>assistant<|channel|>final<|message|>2 + 2 = 4.<|return|>
```

## Reasoning Levels

Control via system message:
- `Reasoning: low` - Fast, minimal chain-of-thought
- `Reasoning: medium` - Balanced (default)
- `Reasoning: high` - Deep reasoning, more steps

## Function Calling

Tools defined in TypeScript-like syntax in developer message:
```
namespace functions {
  // Description
  type function_name = (_: {
    param: string,
    optional?: number, // default: value
  }) => any;
}
```

Tool calls go to `commentary` channel with `to=functions.function_name` recipient.

## Built-in Tools

### Browser
```
namespace browser {
  type search = (_: {query: string, topn?: number}) => any;
  type open = (_: {id?: number | string, cursor?: number}) => any;
  type find = (_: {pattern: string, cursor?: number}) => any;
}
```

### Python
Execute Python code in stateful Jupyter environment.

## Important Notes

1. **Raw format vs API**: When using vLLM or Ollama APIs, the framework handles token rendering
2. **Analysis channel safety**: Content in analysis channel is NOT safety-filtered
3. **CoT handling**: Drop analysis channel when sampling next turn (unless tool calling)
4. **Stop token normalization**: Replace `<|return|>` with `<|end|>` in conversation history

## Cross-References

- Used in: [harmony_integration.md](../architecture/harmony_integration.md)
- API: [harmony_python_api.md](harmony_python_api.md)
- Implementation: Elaboration 01
- Decision: CLAUDE.md Decision #10

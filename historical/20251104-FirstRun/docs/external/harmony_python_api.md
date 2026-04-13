# openai-harmony Python API Reference

**Source**: OpenAI harmony documentation
**Retrieved**: 2025-11-14
**Purpose**: Python bindings for harmony response format rendering and parsing

## Installation

```bash
pip install openai-harmony
```

## Core Workflow

```python
from openai_harmony import (
    load_harmony_encoding,
    HarmonyEncodingName,
    Conversation,
    Message,
    Role,
    SystemContent,
    DeveloperContent,
)

# 1. Create messages
system = Message.from_role_and_content(Role.SYSTEM, SystemContent.new())
user = Message.from_role_and_content(Role.USER, "What is 2 + 2?")
convo = Conversation.from_messages([system, user])

# 2. Render to tokens
encoding = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS)
tokens = encoding.render_conversation_for_completion(convo, Role.ASSISTANT)

# 3. Generate (with vLLM, Ollama, etc.)
# ... model generates new_tokens ...

# 4. Parse back to messages
parsed = encoding.parse_messages_from_completion_tokens(new_tokens, Role.ASSISTANT)
```

## Key Classes

### Role
Enum: `USER`, `ASSISTANT`, `SYSTEM`, `DEVELOPER`, `TOOL`

### ReasoningEffort
Enum: `LOW`, `MEDIUM`, `HIGH`

### SystemContent
```python
SystemContent(
    model_identity: str = "You are ChatGPT...",
    reasoning_effort: ReasoningEffort = ReasoningEffort.MEDIUM,
    conversation_start_date: Optional[str] = None,
    knowledge_cutoff: str = "2024-06",
    channel_config: ChannelConfig = ...,
    tools: Optional[dict] = None,
)
```

**Fluent builders**:
- `.with_model_identity(str)`
- `.with_reasoning_effort(ReasoningEffort)`
- `.with_required_channels(list[str])`
- `.with_browser_tool()`
- `.with_python_tool()`

### DeveloperContent
```python
DeveloperContent(
    instructions: Optional[str] = None,
    tools: Optional[dict] = None,
)
```

**Methods**:
- `.with_instructions(str)`
- `.with_function_tools(list[ToolDescription])`

### Message
```python
Message(
    author: Author,
    content: List[Content],
    channel: Optional[str] = None,
    recipient: Optional[str] = None,
    content_type: Optional[str] = None,
)
```

**Constructors**:
- `Message.from_role_and_content(role, content)`
- `Message.from_author_and_content(author, content)`

**Serialization**:
- `.to_dict()` → JSON dict
- `Message.from_dict(dict)` → Message

### Conversation
```python
Conversation(messages: List[Message])
```

**Constructors**:
- `Conversation.from_messages(list)`

**Serialization**:
- `.to_json()` → JSON string
- `Conversation.from_json(str)` → Conversation

## HarmonyEncoding

```python
encoding = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS)
```

### Rendering Methods

**For completion** (most common):
```python
tokens = encoding.render_conversation_for_completion(
    conversation,
    next_turn_role,
    config=None
)
```

**For training**:
```python
tokens = encoding.render_conversation_for_training(conversation, config=None)
```

**Single message**:
```python
tokens = encoding.render(message)
```

### Parsing Methods

**From tokens**:
```python
messages = encoding.parse_messages_from_completion_tokens(
    tokens,
    role=None,
    strict=True  # False for permissive parsing
)
```

**Decoding**:
```python
text = encoding.decode_utf8(tokens)
```

### Stop Tokens

```python
stops = encoding.stop_tokens()  # All stop tokens
action_stops = encoding.stop_tokens_for_assistant_actions()  # For tool calling
```

## StreamableParser

For incremental parsing during generation:

```python
from openai_harmony import StreamableParser

parser = StreamableParser(encoding, role=Role.ASSISTANT, strict=False)

for token in new_tokens:
    parser.process(token)
    print(parser.current_content)  # Incremental content
    print(parser.current_channel)  # Current channel
    print(parser.last_content_delta)  # Latest addition
```

**Properties**:
- `current_role`
- `current_channel`
- `current_content`
- `current_content_type`
- `current_recipient`
- `last_content_delta`
- `state` (StreamState enum)
- `tokens` (accumulated)

## Tool Definitions

```python
from openai_harmony import ToolDescription

tool = ToolDescription.new(
    "get_weather",
    "Gets current weather",
    parameters={
        "type": "object",
        "properties": {
            "city": {"type": "string"},
            "units": {"type": "string", "enum": ["C", "F"]},
        },
        "required": ["city"]
    }
)
```

## Configuration

### RenderConversationConfig
```python
RenderConversationConfig(auto_drop_analysis=True)
```

Controls whether to automatically drop analysis channel in subsequent turns.

### ChannelConfig
```python
ChannelConfig.require_channels(["analysis", "commentary", "final"])
```

## Common Patterns

### Basic Chat
```python
system = Message.from_role_and_content(
    Role.SYSTEM,
    SystemContent.new().with_reasoning_effort(ReasoningEffort.LOW)
)
developer = Message.from_role_and_content(
    Role.DEVELOPER,
    DeveloperContent.new().with_instructions("Be concise")
)
user = Message.from_role_and_content(Role.USER, "Hello!")

convo = Conversation.from_messages([system, developer, user])
encoding = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS)
tokens = encoding.render_conversation_for_completion(convo, Role.ASSISTANT)
```

### With Function Calling
```python
tools = [ToolDescription.new("get_weather", "Get weather", {...})]

developer = DeveloperContent.new()\
    .with_instructions("Use tools when needed")\
    .with_function_tools(tools)

system = SystemContent.new()  # Automatically adds tool channel config
```

### Parsing Response
```python
# After generation
output_tokens = [...]  # From vLLM or other generator
messages = encoding.parse_messages_from_completion_tokens(
    output_tokens,
    Role.ASSISTANT,
    strict=False  # Permissive for malformed output
)

for msg in messages:
    if msg.channel == "final":
        print(msg.content)  # User-facing output
    elif msg.channel == "analysis":
        print(msg.content)  # Reasoning (don't show user!)
```

## Exception Handling

```python
try:
    tokens = encoding.render_conversation_for_completion(convo, Role.ASSISTANT)
    parsed = encoding.parse_messages_from_completion_tokens(tokens, Role.ASSISTANT)
except RuntimeError as e:
    print(f"Rendering/parsing error: {e}")
except ValueError as e:
    print(f"Invalid argument: {e}")
```

## Cross-References

- Format spec: [harmony_format.md](harmony_format.md)
- Our usage: [harmony_integration.md](../architecture/harmony_integration.md)
- Implementation: Elaboration 01
- Decision: CLAUDE.md Decision #10

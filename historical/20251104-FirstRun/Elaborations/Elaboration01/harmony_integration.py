"""
Harmony Integration Implementation (vLLM version)

This module handles construction of harmony-format messages for gpt-oss models
using proper token rendering via openai_harmony library, and parsing of responses
with analysis and final channels.
"""

from typing import List
from pydantic import BaseModel, Field
from openai_harmony import (
    load_harmony_encoding,
    HarmonyEncodingName,
    Conversation,
    Message,
    Role,
    SystemContent,
    DeveloperContent,
)
import json
from vllm import SamplingParams


class CategoryResult(BaseModel):
    """Result from a category extraction"""
    match: str = Field(..., pattern="^(yes|maybe|no)$")
    blockquotes: list[str]


class HarmonyResponse(BaseModel):
    """Expected structure from harmony format response"""
    analysis_channel: str = ""  # Reasoning trace
    final_channel: str = ""     # JSON output

    def get_category_result(self) -> CategoryResult:
        """Parse final channel as CategoryResult"""
        # Try to extract JSON from markdown formatting
        json_content = self.final_channel
        if "```json" in json_content:
            json_content = json_content.split("```json")[1].split("```")[0].strip()
        elif "```" in json_content:
            json_content = json_content.split("```")[1].split("```")[0].strip()

        parsed = json.loads(json_content)
        return CategoryResult.model_validate(parsed)


def construct_harmony_conversation(
    system_prompt: str,
    category_prompt: str,
    document_content: str,
    reasoning_effort: str = "Medium"
) -> tuple[List[int], List[int]]:
    """
    Construct harmony-format conversation using proper token rendering.

    Args:
        system_prompt: Universal extraction instructions
        category_prompt: Category-specific instructions from YAML
        document_content: The markdown document to analyse
        reasoning_effort: One of "Low", "Medium", "High"

    Returns:
        Tuple of (prefill_ids, stop_token_ids) for vLLM generation
    """
    # Load harmony encoding
    encoding = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS)

    # Build conversation with proper harmony structure
    # System message with reasoning effort
    system_content = SystemContent.new().with_reasoning_effort(reasoning_effort)

    # Developer message with category instructions
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

    # Build conversation
    conversation = Conversation.from_messages([
        Message.from_role_and_content(Role.SYSTEM, system_content),
        Message.from_role_and_content(Role.DEVELOPER, developer_content),
    ])

    # Render to tokens for vLLM
    prefill_ids = encoding.render_conversation_for_completion(conversation, Role.ASSISTANT)
    stop_token_ids = encoding.stop_tokens_for_assistant_actions()

    return prefill_ids, stop_token_ids


def create_sampling_params(
    stop_token_ids: List[int],
    max_tokens: int = 512,
    temperature: float = 0.0
) -> SamplingParams:
    """
    Create vLLM sampling parameters for harmony generation.

    Args:
        stop_token_ids: List of token IDs to stop generation
        max_tokens: Maximum tokens to generate
        temperature: Sampling temperature (0.0 = deterministic)

    Returns:
        SamplingParams configured for harmony format
    """
    return SamplingParams(
        max_tokens=max_tokens,
        temperature=temperature,
        stop_token_ids=stop_token_ids,
    )


def parse_harmony_response(output_tokens: List[int]) -> HarmonyResponse:
    """
    Parse vLLM output tokens to extract analysis and final channels.

    Args:
        output_tokens: Token IDs from vLLM generate()

    Returns:
        HarmonyResponse with analysis_channel and final_channel populated
    """
    # Load encoding for parsing
    encoding = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS)

    # Parse messages from completion tokens
    messages = encoding.parse_messages_from_completion_tokens(
        output_tokens,
        Role.ASSISTANT
    )

    # Extract channels from parsed messages
    analysis = ""
    final = ""

    for message in messages:
        msg_dict = message.to_dict()

        # Check for analysis channel
        if msg_dict.get("channel") == "analysis":
            if "content" in msg_dict:
                content = msg_dict["content"]
                # Content is a list of content items
                if isinstance(content, list):
                    analysis = "".join(item.get("text", "") for item in content if item.get("type") == "text")
                else:
                    analysis = content

        # Check for final channel
        elif msg_dict.get("channel") == "final":
            if "content" in msg_dict:
                content = msg_dict["content"]
                # Content is a list of content items
                if isinstance(content, list):
                    final = "".join(item.get("text", "") for item in content if item.get("type") == "text")
                else:
                    final = content

    return HarmonyResponse(
        analysis_channel=analysis,
        final_channel=final
    )

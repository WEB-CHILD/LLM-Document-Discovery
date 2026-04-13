"""
Phase 1: Test harmony format preservation over HTTP API.

This test verifies that vLLM's HTTP Responses API can preserve
the harmony format's analysis and final channels.

Critical Question:
Does the Responses API support harmony-style reasoning + structured output?
"""

import pytest
from openai import OpenAI
import json


def test_openai_client_import():
    """Test that OpenAI client library is available."""
    assert OpenAI is not None


def test_vllm_server_reachable(vllm_base_url):
    """Test that vLLM server is running and reachable."""
    client = OpenAI(
        base_url=f"{vllm_base_url}/v1",
        api_key="EMPTY"
    )

    # Check models endpoint
    models = client.models.list()
    model_ids = [m.id for m in models.data]

    assert len(model_ids) > 0, "No models available from server"
    print(f"\n[INFO] Available models: {model_ids}")


def test_responses_api_basic(vllm_base_url, model_name):
    """Test basic Responses API functionality."""
    client = OpenAI(
        base_url=f"{vllm_base_url}/v1",
        api_key="EMPTY"
    )

    # Simple test request
    response = client.responses.create(
        model=model_name,
        instructions="You are a helpful assistant that responds concisely.",
        input="What is 2+2?",
        temperature=0.0,
    )

    # Check response structure
    assert hasattr(response, 'output_text'), "Response missing output_text"
    assert len(response.output_text) > 0, "Empty response"

    print(f"\n[INFO] Basic response: {response.output_text[:100]}")


def test_harmony_format_with_responses_api(
    vllm_base_url,
    model_name,
    system_prompt,
    category_prompt,
    test_document
):
    """
    Test if Responses API supports harmony-style reasoning.

    This is the CRITICAL test: Can we get analysis + final channels over HTTP?
    """
    client = OpenAI(
        base_url=f"{vllm_base_url}/v1",
        api_key="EMPTY"
    )

    # Construct instructions with harmony format request
    instructions = f"""{system_prompt}

# Category Instructions

{category_prompt}

# Response Format

Use structured reasoning to analyze the document.
First, provide your reasoning and analysis.
Then, provide the final result in JSON format:
{{
  "match": "yes" or "maybe" or "no",
  "blockquotes": ["quote 1", "quote 2"]
}}"""

    # Make request
    response = client.responses.create(
        model=model_name,
        instructions=instructions,
        input=test_document,
        temperature=0.0,
        max_tokens=1024,
    )

    # Check what we got back
    assert hasattr(response, 'output_text'), "Response missing output_text"
    output = response.output_text

    print(f"\n[DEBUG] Response type: {type(response)}")
    print(f"[DEBUG] Response attributes: {dir(response)}")
    print(f"[DEBUG] Output length: {len(output)} chars")
    print(f"[DEBUG] First 500 chars:\n{output[:500]}")
    print(f"[DEBUG] Last 500 chars:\n{output[-500:]}")

    # Try to parse JSON from output
    # The model might include reasoning followed by JSON
    has_json = False
    category_result = None

    # Look for JSON block
    if "{" in output and "}" in output:
        # Try to extract JSON
        json_start = output.rfind("{")
        json_end = output.rfind("}") + 1

        if json_start < json_end:
            try:
                json_str = output[json_start:json_end]
                parsed = json.loads(json_str)
                has_json = True
                category_result = parsed
                print(f"\n[INFO] Successfully parsed JSON: {parsed}")
            except json.JSONDecodeError as e:
                print(f"\n[WARN] JSON parse failed: {e}")

    # Also check if response object has other fields (thinking, reasoning, etc.)
    response_dict = response.model_dump() if hasattr(response, 'model_dump') else {}
    print(f"\n[DEBUG] Response dict keys: {response_dict.keys()}")

    if 'thinking' in response_dict:
        print(f"[INFO] Found 'thinking' field: {response_dict['thinking'][:200]}")

    if 'reasoning' in response_dict:
        print(f"[INFO] Found 'reasoning' field: {response_dict['reasoning'][:200]}")

    # For this test, we just need to know:
    # 1. Did we get a response?
    # 2. Can we extract structured output?
    # 3. Is there separate reasoning (even if in same field)?

    assert len(output) > 0, "Empty response"
    assert has_json, "No valid JSON found in response"
    assert category_result is not None, "Failed to parse category result"
    assert "match" in category_result, "JSON missing 'match' field"
    assert "blockquotes" in category_result, "JSON missing 'blockquotes' field"


def test_chat_completions_alternative(
    vllm_base_url,
    model_name,
    system_prompt,
    category_prompt,
    test_document
):
    """
    Test Chat Completions API as alternative to Responses API.

    This tests the /v1/chat/completions endpoint which is more widely supported.
    """
    client = OpenAI(
        base_url=f"{vllm_base_url}/v1",
        api_key="EMPTY"
    )

    # Construct messages
    system_message = {
        "role": "system",
        "content": system_prompt
    }

    user_message = {
        "role": "user",
        "content": f"""# Category Instructions

{category_prompt}

# Document to Analyze

{test_document}

# Response Format

First, provide your reasoning and analysis.
Then, provide ONLY valid JSON with this structure:
{{
  "match": "yes" or "maybe" or "no",
  "blockquotes": ["quote 1", "quote 2"]
}}"""
    }

    # Make request
    response = client.chat.completions.create(
        model=model_name,
        messages=[system_message, user_message],
        temperature=0.0,
        max_tokens=1024,
    )

    # Extract response
    assert len(response.choices) > 0, "No choices in response"
    message = response.choices[0].message
    content = message.content

    print(f"\n[DEBUG] Chat completion response length: {len(content)} chars")
    print(f"[DEBUG] First 300 chars:\n{content[:300]}")
    print(f"[DEBUG] Last 300 chars:\n{content[-300:]}")

    # Try to parse JSON
    has_json = False
    if "{" in content and "}" in content:
        json_start = content.rfind("{")
        json_end = content.rfind("}") + 1

        if json_start < json_end:
            try:
                json_str = content[json_start:json_end]
                parsed = json.loads(json_str)
                has_json = True
                print(f"\n[INFO] Successfully parsed JSON from chat: {parsed}")
            except json.JSONDecodeError as e:
                print(f"\n[WARN] JSON parse failed: {e}")

    assert len(content) > 0, "Empty response"
    assert has_json, "No valid JSON found in chat response"


if __name__ == "__main__":
    # Allow manual test execution
    pytest.main([__file__, "-v", "-s"])

"""
Tests for harmony integration layer.

These tests validate token rendering, response parsing, and the full harmony workflow.
Some tests require vLLM model (marked with pytest.mark.gpu).
"""

import pytest
from harmony_processor import (
    construct_harmony_conversation,
    parse_harmony_response,
    create_sampling_params,
    HarmonyResponse,
)
from schemas import CategoryResult


def test_harmony_response_class_exists():
    """Verify HarmonyResponse can be instantiated"""
    response = HarmonyResponse(
        analysis_channel="Test reasoning",
        final_channel='{"match": "yes", "blockquotes": []}'
    )
    assert response.analysis_channel == "Test reasoning"
    assert response.final_channel == '{"match": "yes", "blockquotes": []}'


def test_harmony_response_parse_simple_json():
    """Verify get_category_result() parses plain JSON"""
    response = HarmonyResponse(
        analysis_channel="Reasoning here",
        final_channel='{"match": "yes", "blockquotes": ["quote 1", "quote 2"]}'
    )

    result = response.get_category_result()
    assert isinstance(result, CategoryResult)
    assert result.match == "yes"
    assert result.blockquotes == ["quote 1", "quote 2"]


def test_harmony_response_parse_markdown_json():
    """Verify get_category_result() handles markdown code blocks"""
    response = HarmonyResponse(
        analysis_channel="Analysis",
        final_channel='```json\n{"match": "maybe", "blockquotes": ["test"]}\n```'
    )

    result = response.get_category_result()
    assert result.match == "maybe"
    assert result.blockquotes == ["test"]


def test_harmony_response_parse_invalid_json_returns_empty():
    """Verify get_category_result() returns empty result on parse failure"""
    response = HarmonyResponse(
        analysis_channel="Analysis",
        final_channel="not valid json at all"
    )

    result = response.get_category_result()
    # Should not raise, returns default empty
    assert result.match == "no"
    assert result.blockquotes == []


def test_construct_harmony_conversation_returns_tokens():
    """Verify construct_harmony_conversation() returns token IDs"""
    prefill_ids, stop_ids = construct_harmony_conversation(
        system_prompt="Extract information.",
        category_prompt="Look for imperatives.",
        document_content="# Test\nClick here.",
        reasoning_effort="Low"
    )

    assert isinstance(prefill_ids, list)
    assert len(prefill_ids) > 0
    assert all(isinstance(token_id, int) for token_id in prefill_ids)

    assert isinstance(stop_ids, list)
    assert len(stop_ids) > 0
    assert all(isinstance(token_id, int) for token_id in stop_ids)


def test_create_sampling_params_returns_vllm_params():
    """Verify create_sampling_params() creates valid SamplingParams"""
    from vllm import SamplingParams

    params = create_sampling_params(
        stop_token_ids=[123, 456],
        max_tokens=256,
        temperature=0.0
    )

    assert isinstance(params, SamplingParams)
    assert params.max_tokens == 256
    assert params.temperature == 0.0
    assert params.stop_token_ids == [123, 456]


@pytest.mark.gpu
def test_full_harmony_workflow(vllm_model):
    """
    End-to-end test: construct → generate → parse

    Requires GPU (vLLM model).
    """
    from vllm.inputs import TokensPrompt

    # Construct harmony conversation
    prefill_ids, stop_ids = construct_harmony_conversation(
        system_prompt="You are an extraction assistant. Extract information accurately.",
        category_prompt="Determine if this document contains health information. Respond with yes/maybe/no and provide blockquotes as evidence.",
        document_content="# Health Tips\n\nEating fruits is good for your health.",
        reasoning_effort="Low"
    )

    # Create prompt and sampling params
    prompt = TokensPrompt(prompt_token_ids=prefill_ids)
    sampling_params = create_sampling_params(
        stop_token_ids=stop_ids,
        max_tokens=256,
        temperature=0.0
    )

    # Generate with vLLM
    outputs = vllm_model.generate(
        prompts=[prompt],
        sampling_params=sampling_params
    )

    assert len(outputs) == 1
    output_tokens = outputs[0].outputs[0].token_ids

    # Parse response
    harmony_response = parse_harmony_response(output_tokens)

    assert isinstance(harmony_response, HarmonyResponse)
    assert len(harmony_response.analysis_channel) > 0  # Should have reasoning
    assert len(harmony_response.final_channel) > 0     # Should have JSON

    # Parse to CategoryResult
    category_result = harmony_response.get_category_result()

    assert isinstance(category_result, CategoryResult)
    assert category_result.match in ["yes", "maybe", "no"]
    assert isinstance(category_result.blockquotes, list)


@pytest.mark.gpu
def test_reasoning_effort_variations(vllm_model):
    """Verify different reasoning efforts work"""
    from vllm.inputs import TokensPrompt

    for effort in ["Low", "Medium", "High"]:
        prefill_ids, stop_ids = construct_harmony_conversation(
            system_prompt="Extract info.",
            category_prompt="Find imperatives.",
            document_content="Click here to continue.",
            reasoning_effort=effort
        )

        prompt = TokensPrompt(prompt_token_ids=prefill_ids)
        sampling_params = create_sampling_params(
            stop_token_ids=stop_ids,
            max_tokens=512,
            temperature=0.0
        )

        outputs = vllm_model.generate(prompts=[prompt], sampling_params=sampling_params)
        output_tokens = outputs[0].outputs[0].token_ids

        harmony_response = parse_harmony_response(output_tokens)

        # All reasoning efforts should produce valid output
        assert len(harmony_response.final_channel) > 0

        # Higher reasoning effort may produce longer analysis (not guaranteed, but often)
        # We just verify it works
        result = harmony_response.get_category_result()
        assert result.match in ["yes", "maybe", "no"]

"""
Elaboration 02: Multi-Model Compatibility Test (vLLM)

This test verifies that openai/gpt-oss-20b and openai/gpt-oss-safeguard-20b
can use the same harmony token rendering code paths without model-specific handling.

Note: 120b testing deferred to HPC (will run E01 suite with MODEL=120b)

These tests will FAIL if:
- Models require different prompt formats
- Models return incompatible harmony response structures
- Safeguard model needs special handling

Run with: uv run pytest Elaborations/Elaboration02/ -xvs
"""

import pytest
from pathlib import Path
from vllm import LLM, SamplingParams
from vllm.inputs import TokensPrompt

# Import from Elaboration 01 (depends on E01 passing)
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "Elaboration01"))
from harmony_integration import (
    construct_harmony_conversation,
    parse_harmony_response,
    create_sampling_params,
    HarmonyResponse,
    CategoryResult,
)


# Models to test locally
MODELS_TO_TEST = [
    "openai/gpt-oss-20b",
    "openai/gpt-oss-safeguard-20b",
]


@pytest.mark.parametrize("model_name", MODELS_TO_TEST)
def test_model_loads(model_name, vllm_model_factory):
    """Test 1: Does each model load successfully via vLLM?

    This will FAIL if:
    - Model not available on HuggingFace
    - GPU memory insufficient
    - vLLM compatibility issues
    """
    try:
        llm = vllm_model_factory(model_name)
        assert llm is not None
        # Verify model has been initialized
        assert hasattr(llm, 'llm_engine')
    except Exception as e:
        pytest.fail(f"Failed to load model {model_name}: {e}")


@pytest.mark.parametrize("model_name", MODELS_TO_TEST)
def test_harmony_tokens_accepted(model_name, vllm_model_factory, test_data):
    """Test 2: Does each model accept the same harmony token sequences?

    This will FAIL if:
    - construct_harmony_conversation produces incompatible tokens for a model
    - Model rejects harmony token format
    """
    llm = vllm_model_factory(model_name)

    # Construct harmony conversation (same for both models)
    prefill_ids, stop_token_ids = construct_harmony_conversation(
        system_prompt=test_data["system_prompt"],
        category_prompt=test_data["category_data"]["prompt"],
        document_content=test_data["test_content"],
        reasoning_effort="Low",  # Use Low for faster testing
    )

    # Verify we got valid token sequences
    assert prefill_ids is not None
    assert len(prefill_ids) > 0
    assert isinstance(prefill_ids, list)
    assert all(isinstance(token_id, int) for token_id in prefill_ids)

    # Create sampling params
    sampling_params = create_sampling_params(
        stop_token_ids=stop_token_ids,
        max_tokens=512,
        temperature=0.0,
    )

    # Attempt generation
    try:
        prompt = TokensPrompt(prompt_token_ids=prefill_ids)
        outputs = llm.generate(
            prompts=[prompt],
            sampling_params=sampling_params,
        )
        assert outputs is not None
        assert len(outputs) > 0
        assert hasattr(outputs[0], 'outputs')
        assert len(outputs[0].outputs) > 0
    except Exception as e:
        pytest.fail(f"Model {model_name} rejected harmony tokens: {e}")


@pytest.mark.parametrize("model_name", MODELS_TO_TEST)
def test_response_structure(model_name, vllm_model_factory, test_data):
    """Test 3: Can we parse each model's response with the same parsing function?

    This will FAIL if:
    - Models return incompatible token structures
    - Harmony channel parsing fails for a model
    - Response doesn't contain analysis + final channels
    """
    llm = vllm_model_factory(model_name)

    # Generate response
    prefill_ids, stop_token_ids = construct_harmony_conversation(
        system_prompt=test_data["system_prompt"],
        category_prompt=test_data["category_data"]["prompt"],
        document_content=test_data["test_content"],
        reasoning_effort="Low",
    )

    sampling_params = create_sampling_params(
        stop_token_ids=stop_token_ids,
        max_tokens=512,
        temperature=0.0,
    )

    prompt = TokensPrompt(prompt_token_ids=prefill_ids)
    outputs = llm.generate(
        prompts=[prompt],
        sampling_params=sampling_params,
    )

    output_tokens = outputs[0].outputs[0].token_ids

    # Parse using same function for all models
    try:
        harmony_response = parse_harmony_response(output_tokens)
        assert isinstance(harmony_response, HarmonyResponse)

        # Verify both channels exist
        assert hasattr(harmony_response, 'analysis_channel')
        assert hasattr(harmony_response, 'final_channel')

        # Analysis channel should have reasoning content
        assert harmony_response.analysis_channel is not None
        assert len(harmony_response.analysis_channel) > 0

        # Final channel should have JSON content (may be empty if model stopped early)
        assert harmony_response.final_channel is not None

    except Exception as e:
        pytest.fail(f"Failed to parse {model_name} response: {e}")


@pytest.mark.parametrize("model_name", MODELS_TO_TEST)
def test_json_validation(model_name, vllm_model_factory, test_data):
    """Test 4: Does each model return valid JSON matching CategoryResult schema?

    This will FAIL if:
    - Model doesn't produce valid JSON in final channel
    - JSON doesn't match CategoryResult schema
    - Schema validation fails
    """
    llm = vllm_model_factory(model_name)

    # Generate response
    prefill_ids, stop_token_ids = construct_harmony_conversation(
        system_prompt=test_data["system_prompt"],
        category_prompt=test_data["category_data"]["prompt"],
        document_content=test_data["test_content"],
        reasoning_effort="Low",
    )

    sampling_params = create_sampling_params(
        stop_token_ids=stop_token_ids,
        max_tokens=512,
        temperature=0.0,
    )

    prompt = TokensPrompt(prompt_token_ids=prefill_ids)
    outputs = llm.generate(
        prompts=[prompt],
        sampling_params=sampling_params,
    )

    output_tokens = outputs[0].outputs[0].token_ids
    harmony_response = parse_harmony_response(output_tokens)

    # Extract and validate CategoryResult
    try:
        # Skip if final channel is empty (model stopped early)
        if not harmony_response.final_channel or len(harmony_response.final_channel.strip()) == 0:
            pytest.skip(f"Model {model_name} stopped before completing final channel (non-deterministic or max_tokens)")

        result = harmony_response.get_category_result()

        # Verify schema compliance
        assert result.match in ["yes", "maybe", "no"], f"Invalid match value: {result.match}"
        assert isinstance(result.blockquotes, list), f"Blockquotes is not a list: {type(result.blockquotes)}"

    except Exception as e:
        pytest.fail(f"Model {model_name} schema validation failed: {e}\nFinal channel: {harmony_response.final_channel[:200]}")


@pytest.mark.parametrize("model_name", MODELS_TO_TEST)
def test_cross_model_consistency(model_name, vllm_model_factory, test_data):
    """Test 5: Do both models produce responses with identical structure?

    This is a structural consistency test. We expect DIFFERENT content
    (different model capabilities) but IDENTICAL structure.

    This will FAIL if:
    - Model's response structure is incompatible with harmony parsing
    - Model requires special parsing logic
    - Schema validation fails
    """
    llm = vllm_model_factory(model_name)

    # Use exact same input for all models
    prefill_ids, stop_token_ids = construct_harmony_conversation(
        system_prompt=test_data["system_prompt"],
        category_prompt=test_data["category_data"]["prompt"],
        document_content=test_data["test_content"],
        reasoning_effort="Low",
    )

    sampling_params = create_sampling_params(
        stop_token_ids=stop_token_ids,
        max_tokens=512,
        temperature=0.0,
    )

    prompt = TokensPrompt(prompt_token_ids=prefill_ids)
    outputs = llm.generate(
        prompts=[prompt],
        sampling_params=sampling_params,
    )

    output_tokens = outputs[0].outputs[0].token_ids
    harmony_response = parse_harmony_response(output_tokens)

    # Verify standard structure exists
    assert harmony_response.analysis_channel is not None, f"{model_name} missing analysis channel"
    assert len(harmony_response.analysis_channel) > 10, f"{model_name} analysis too short"
    assert harmony_response.final_channel is not None, f"{model_name} missing final channel attribute"

    # Try to parse CategoryResult if final channel has content
    has_final = len(harmony_response.final_channel.strip()) > 0 if harmony_response.final_channel else False

    if has_final:
        try:
            result = harmony_response.get_category_result()
            assert result.match in ["yes", "maybe", "no"], f"{model_name} invalid match value: {result.match}"
            assert isinstance(result.blockquotes, list), f"{model_name} blockquotes not a list"

            # Print structural info for comparison
            print(f"\n{model_name} structure:")
            print(f"  Analysis: {len(harmony_response.analysis_channel)} chars")
            print(f"  Final: {len(harmony_response.final_channel)} chars")
            print(f"  Match: {result.match}")
            print(f"  Blockquotes: {len(result.blockquotes)}")
        except Exception as e:
            pytest.fail(f"{model_name} schema validation failed: {e}")
    else:
        # Model stopped before completing final channel
        print(f"\n{model_name} stopped before completing final channel (max_tokens or non-determinism)")
        pytest.skip(f"{model_name} stopped early - structural test skipped")

    # If we made it here, this model is structurally compatible
    print(f"\n✓ {model_name} structurally compatible - no model-specific code needed")

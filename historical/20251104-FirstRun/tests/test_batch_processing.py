"""
Tests for batch processing of multiple categories.

Validates extract_all_categories_batch() function that processes
all categories for a document in a single vLLM call.
"""

import pytest
from harmony_processor import extract_all_categories_batch
from schemas import CategoryResult


@pytest.mark.gpu
def test_batch_extract_multiple_categories(vllm_model):
    """
    Test batch extraction of multiple categories for a single document.

    Verifies that all categories are processed correctly in a single vLLM call
    and that results are properly paired with category IDs.
    """
    # Test document with clear imperative content
    document = """# Welcome to Our Site

Click here to continue.
Please enter your name below.
Submit the form when ready.

This site was created in 1998.
"""

    # System prompt
    system_prompt = "You are a text extraction tool. Extract information accurately."

    # Multiple test categories
    categories = [
        {
            "id": 1,
            "name": "imperative_verbs",
            "description": "Commands and instructions",
            "prompt": "Find all sentences containing imperative verbs (commands). Mark as 'yes' if imperatives present, 'no' if absent."
        },
        {
            "id": 2,
            "name": "temporal_references",
            "description": "References to time periods",
            "prompt": "Find references to specific years or time periods. Mark as 'yes' if temporal references present, 'no' if absent."
        },
        {
            "id": 3,
            "name": "questions",
            "description": "Interrogative sentences",
            "prompt": "Find questions or interrogative sentences. Mark as 'yes' if questions present, 'no' if absent."
        }
    ]

    # Batch extract all categories
    results = extract_all_categories_batch(
        llm=vllm_model,
        document_content=document,
        categories=categories,
        system_prompt=system_prompt,
        reasoning_effort="Low"
    )

    # Verify we got results for all categories
    assert len(results) == 3

    # Verify structure: list of (category_id, HarmonyResponse) tuples
    category_ids_returned = [cat_id for cat_id, _ in results]
    assert category_ids_returned == [1, 2, 3]

    # Verify each result has valid structure
    for category_id, harmony_response in results:
        assert category_id in [1, 2, 3]
        assert len(harmony_response.analysis_channel) > 0  # Should have reasoning
        assert len(harmony_response.final_channel) > 0     # Should have JSON

        # Parse to CategoryResult
        result = harmony_response.get_category_result()
        assert isinstance(result, CategoryResult)
        assert result.match in ["yes", "maybe", "no"]
        assert isinstance(result.blockquotes, list)

    # Verify expected matches based on content
    results_by_id = {cat_id: harmony_response for cat_id, harmony_response in results}

    # Category 1 (imperatives): Should be "yes" - document has "Click", "Please enter", "Submit"
    cat1_result = results_by_id[1].get_category_result()
    assert cat1_result.match in ["yes", "maybe"]  # Allow maybe if model uncertain

    # Category 2 (temporal): Should be "yes" - document mentions "1998"
    cat2_result = results_by_id[2].get_category_result()
    assert cat2_result.match in ["yes", "maybe"]

    # Category 3 (questions): Should be "no" - no questions in document
    cat3_result = results_by_id[3].get_category_result()
    assert cat3_result.match in ["no", "maybe"]  # Allow maybe if model uncertain


@pytest.mark.gpu
def test_batch_extract_with_config_defaults(vllm_model):
    """
    Test that batch extraction uses config defaults when reasoning_effort not specified.
    """
    document = "Click here."
    system_prompt = "Extract info."
    categories = [
        {
            "id": 1,
            "name": "test",
            "description": "Test category",
            "prompt": "Find imperatives."
        }
    ]

    # Call without reasoning_effort (should use config.REASONING_EFFORT)
    results = extract_all_categories_batch(
        llm=vllm_model,
        document_content=document,
        categories=categories,
        system_prompt=system_prompt
        # reasoning_effort not specified
    )

    assert len(results) == 1
    category_id, harmony_response = results[0]
    assert category_id == 1
    assert len(harmony_response.final_channel) > 0


@pytest.mark.gpu
def test_batch_extract_single_category(vllm_model):
    """
    Test that batch extraction works correctly with just one category.

    Edge case: batch of 1 should work the same as batch of many.
    """
    document = "Test document."
    system_prompt = "Extract."
    categories = [
        {
            "id": 5,
            "name": "single",
            "description": "Single test",
            "prompt": "Find anything."
        }
    ]

    results = extract_all_categories_batch(
        llm=vllm_model,
        document_content=document,
        categories=categories,
        system_prompt=system_prompt,
        reasoning_effort="Low"
    )

    assert len(results) == 1
    category_id, harmony_response = results[0]
    assert category_id == 5

    result = harmony_response.get_category_result()
    assert result.match in ["yes", "maybe", "no"]

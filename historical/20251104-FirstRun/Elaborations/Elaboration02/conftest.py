"""
Pytest configuration for Elaboration 02: Multi-Model Compatibility (vLLM)

Provides fixtures for testing gpt-oss-20b and gpt-oss-safeguard-20b
with sequential model loading to manage GPU memory constraints.
"""

import sys
from pathlib import Path
import pytest

# Add parent directory to import harmony_integration from E01
elaboration01_path = Path(__file__).parent.parent / "Elaboration01"
sys.path.insert(0, str(elaboration01_path))


@pytest.fixture
def vllm_model_factory():
    """
    Factory fixture to create vLLM models with proper cleanup.

    Function-scoped to allow sequential model loading within same test session.
    Each model is cleaned up after use to free GPU memory for the next model.

    Usage:
        def test_something(vllm_model_factory):
            llm = vllm_model_factory("openai/gpt-oss-20b")
            # ... use model
    """
    from vllm import LLM

    active_models = []

    def _create_model(model_name: str):
        """Load a vLLM model with standard configuration."""
        llm = LLM(
            model=model_name,
            gpu_memory_utilization=0.85,
            trust_remote_code=True,
        )
        active_models.append(llm)
        return llm

    yield _create_model

    # Cleanup: Delete all models and free GPU memory
    for llm in active_models:
        del llm

    # Force GPU memory release
    try:
        import torch
        torch.cuda.empty_cache()
    except ImportError:
        pass  # torch not available, skip cleanup


@pytest.fixture
def test_data():
    """
    Shared test data for all model compatibility tests.

    Returns dict with:
        - system_prompt: str
        - category_data: dict from YAML
        - test_content: str (short document for testing)
    """
    import yaml

    # Load system prompt
    system_prompt_path = Path(__file__).parent.parent.parent / "system_prompt.txt"
    with open(system_prompt_path) as f:
        system_prompt = f.read()

    # Load category prompt (imperative verbs - good test case)
    category_path = Path(__file__).parent.parent.parent / "POC-prompts" / "01_imperative_verbs.yaml"
    with open(category_path) as f:
        category_data = yaml.safe_load(f)

    # Short test content with clear imperative verbs
    test_content = "Click here to learn more. Join us today! Sign up for our newsletter."

    return {
        "system_prompt": system_prompt,
        "category_data": category_data,
        "test_content": test_content,
    }

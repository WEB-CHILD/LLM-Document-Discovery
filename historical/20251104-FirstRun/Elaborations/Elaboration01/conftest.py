"""
Pytest configuration for Elaboration 01

This ensures the local harmony_integration module can be imported and provides
a session-scoped vLLM model instance for all tests.
"""

import sys
from pathlib import Path
import pytest

# Add this directory to Python path so tests can import harmony_integration
sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(scope="session")
def vllm_model():
    """
    Load vLLM model once for entire test session.

    The model remains in GPU memory and is reused across all tests,
    avoiding the 10-30 second startup penalty per test.

    Returns:
        vLLM LLM instance configured for openai/gpt-oss-20b
    """
    from vllm import LLM

    llm = LLM(
        model="openai/gpt-oss-20b",
        gpu_memory_utilization=0.85,
        trust_remote_code=True,
    )

    return llm

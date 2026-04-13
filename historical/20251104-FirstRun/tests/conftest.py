"""
Shared pytest fixtures for testing the boolean index extraction pipeline.

Session-scoped fixtures for expensive resources (vLLM model).
"""

import pytest
from pathlib import Path
import sys
import os

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def vllm_model():
    """
    Session-scoped vLLM model fixture.

    Loads model once for all tests to avoid expensive reloading.
    Requires GPU available.
    """
    pytest.importorskip("vllm", reason="vLLM not available")

    from harmony_processor import init_vllm_model

    # Use 20b model for testing (faster than 120b)
    # Respect VLLM_TENSOR_PARALLEL_SIZE env var (HPC) or default to 1 (local dev)
    llm = init_vllm_model(
        model_name="openai/gpt-oss-20b",
        tensor_parallel_size=int(os.getenv("VLLM_TENSOR_PARALLEL_SIZE", "1")),
        gpu_memory_utilization=0.85,
        trust_remote_code=True
    )

    yield llm

    # Cleanup
    del llm
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


@pytest.fixture(scope="session")
def test_corpus_dir():
    """Path to test corpus directory"""
    return Path(__file__).parent / "fixtures" / "test_corpus"


@pytest.fixture(scope="function")
def test_database(tmp_path):
    """
    Function-scoped test database.

    Creates fresh database for each test to avoid interference.
    """
    from db import init_database

    db_path = tmp_path / "test.db"
    conn = init_database(str(db_path))

    yield conn

    conn.close()


@pytest.fixture(scope="function")
def temp_yaml_dir(tmp_path):
    """
    Temporary YAML directory for testing category loading.

    Returns:
        Path to empty directory for creating test YAML files
    """
    yaml_dir = tmp_path / "test_prompts"
    yaml_dir.mkdir()
    return yaml_dir

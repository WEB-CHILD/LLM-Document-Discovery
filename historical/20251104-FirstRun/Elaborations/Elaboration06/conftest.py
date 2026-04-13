"""
Shared fixtures for Elaboration 06 HTTP API tests.

This module provides pytest fixtures for vLLM server interaction.
"""

import pytest
import os


@pytest.fixture(scope="session")
def vllm_base_url():
    """
    vLLM server base URL.

    Returns:
        Base URL for vLLM OpenAI-compatible server (default: http://localhost:8000)
    """
    return os.getenv("VLLM_BASE_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def model_name():
    """
    Model name to use for requests.

    Returns:
        HuggingFace model ID (default: openai/gpt-oss-20b)
    """
    return os.getenv("GPT_MODEL", "openai/gpt-oss-20b")


@pytest.fixture(scope="module")
def project_root():
    """
    Get project root directory.

    Returns:
        Path to project root
    """
    return os.path.join(os.path.dirname(__file__), "..", "..")


@pytest.fixture(scope="module")
def system_prompt(project_root):
    """
    Load universal system prompt for extraction.

    Returns:
        System prompt text
    """
    prompt_path = os.path.join(project_root, "system_prompt.txt")
    with open(prompt_path, "r") as f:
        return f.read()


@pytest.fixture(scope="module")
def category_prompt(project_root):
    """
    Load test category prompt (imperatives).

    Returns:
        Category-specific prompt text
    """
    import yaml
    prompt_path = os.path.join(project_root, "POC-prompts", "01_imperative_verbs.yaml")
    with open(prompt_path, "r") as f:
        data = yaml.safe_load(f)
    return data["prompt"]


@pytest.fixture(scope="module")
def test_document(project_root):
    """
    Load test document for processing.

    Returns:
        Document content string
    """
    doc_path = os.path.join(project_root, "input", "19961019235833_http_ds.internic.net_80_ds_dsdirofdirs.html.md")
    with open(doc_path, "r") as f:
        return f.read()

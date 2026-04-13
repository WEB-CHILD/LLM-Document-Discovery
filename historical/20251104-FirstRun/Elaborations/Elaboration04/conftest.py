"""
Pytest configuration for Elaboration 04: Batch Processing Performance (vLLM)

Provides fixtures for testing vLLM batch processing with different batch sizes.
"""

import sys
from pathlib import Path
import pytest
import yaml

# Add parent directory to import harmony_integration from E01
elaboration01_path = Path(__file__).parent.parent / "Elaboration01"
sys.path.insert(0, str(elaboration01_path))


@pytest.fixture(scope="session")
def vllm_model():
    """
    Session-scoped vLLM model instance.

    Loads once at start of test session and reuses across all tests
    to avoid model reload overhead (which takes ~15-20 seconds).
    """
    from vllm import LLM

    print("\n🔄 Loading vLLM model (session-scoped, one-time cost)...")
    llm = LLM(
        model="openai/gpt-oss-20b",
        gpu_memory_utilization=0.85,
        trust_remote_code=True,
    )
    print("✅ Model loaded successfully")

    yield llm

    # Cleanup
    del llm
    try:
        import torch
        torch.cuda.empty_cache()
    except ImportError:
        pass


@pytest.fixture(scope="module")
def system_prompt():
    """Load system prompt from root directory."""
    system_prompt_path = Path(__file__).parent.parent.parent / "system_prompt.txt"
    with open(system_prompt_path) as f:
        return f.read()


@pytest.fixture(scope="module")
def category_prompts():
    """
    Load all 15 category prompts from POC-prompts/.

    Returns list of dicts with 'name' and 'prompt' keys.
    """
    prompts_dir = Path(__file__).parent.parent.parent / "POC-prompts"

    # Get all YAML files
    yaml_files = sorted(prompts_dir.glob("*.yaml"))

    categories = []
    for yaml_file in yaml_files:
        with open(yaml_file) as f:
            data = yaml.safe_load(f)
            categories.append({
                "name": yaml_file.stem,
                "prompt": data["prompt"],
            })

    assert len(categories) == 15, f"Expected 15 categories, found {len(categories)}"

    return categories


@pytest.fixture(scope="module")
def test_files():
    """
    Select 5 representative markdown files for testing.

    Selects files of similar size for controlled comparison.
    Returns list of Path objects.
    """
    input_dir = Path(__file__).parent.parent.parent / "input"

    # Get all markdown files
    all_files = list(input_dir.rglob("*.md"))

    if len(all_files) == 0:
        pytest.skip("No markdown files found in input/ directory")

    # Sort by size and select 5 files from the middle (avoid extremes)
    files_by_size = sorted(all_files, key=lambda f: f.stat().st_size)
    middle_index = len(files_by_size) // 2

    # Select 5 files around the median size
    start_index = max(0, middle_index - 2)
    selected_files = files_by_size[start_index:start_index + 5]

    # Ensure we have 5 files
    if len(selected_files) < 5:
        # Fallback: take first 5 files
        selected_files = files_by_size[:5]

    assert len(selected_files) >= 1, "Need at least 1 test file"

    print(f"\n📄 Selected {len(selected_files)} test files:")
    for f in selected_files:
        size_kb = f.stat().st_size / 1024
        print(f"  - {f.name}: {size_kb:.1f} KB")

    return selected_files[:5]  # Return max 5 files


@pytest.fixture(scope="module")
def test_document(test_files):
    """
    Load a single test document (first file from test_files).

    Used for tests that need one document.
    """
    with open(test_files[0]) as f:
        return f.read()

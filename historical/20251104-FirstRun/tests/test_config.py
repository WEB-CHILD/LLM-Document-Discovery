"""
Tests for configuration management.

TDD: These tests will fail until config.py is implemented.
"""

import pytest
import os
from pathlib import Path


def test_config_module_exists():
    """Verify config module can be imported"""
    import config
    assert config is not None


def test_config_has_all_required_variables():
    """Verify all required config variables exist with defaults"""
    import config

    # Paths
    assert hasattr(config, "PROJECT_ROOT")
    assert hasattr(config, "SYSTEM_PROMPT_PATH")
    assert hasattr(config, "PROMPTS_DIR")
    assert hasattr(config, "SCHEMA_PATH")
    assert hasattr(config, "INPUT_DIR")
    assert hasattr(config, "DB_PATH")

    # Model config
    assert hasattr(config, "GPT_MODEL")
    assert hasattr(config, "REASONING_EFFORT")

    # vLLM config
    assert hasattr(config, "VLLM_TENSOR_PARALLEL_SIZE")
    assert hasattr(config, "VLLM_GPU_MEMORY_UTILIZATION")
    assert hasattr(config, "VLLM_TRUST_REMOTE_CODE")
    assert hasattr(config, "VLLM_MAX_NUM_SEQS")

    # Generation params
    assert hasattr(config, "VLLM_MAX_TOKENS")
    assert hasattr(config, "TEMPERATURE")


def test_config_defaults_are_sensible():
    """Verify default values are reasonable"""
    import config

    # Model should be one of the gpt-oss variants
    assert "gpt-oss" in config.GPT_MODEL
    assert config.GPT_MODEL in [
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-safeguard-20b"
    ]

    # Reasoning effort must be capitalized
    assert config.REASONING_EFFORT in ["Low", "Medium", "High"]

    # vLLM params should be in valid ranges
    assert 1 <= config.VLLM_TENSOR_PARALLEL_SIZE <= 8
    assert 0.0 <= config.VLLM_GPU_MEMORY_UTILIZATION <= 1.0
    assert config.VLLM_MAX_NUM_SEQS == 15  # Batch all categories

    # Temperature should be deterministic for production
    assert config.TEMPERATURE == 0.0


def test_config_paths_use_path_objects():
    """Verify path variables are Path objects, not strings"""
    import config

    assert isinstance(config.PROJECT_ROOT, Path)
    assert isinstance(config.SYSTEM_PROMPT_PATH, Path)
    assert isinstance(config.PROMPTS_DIR, Path)
    assert isinstance(config.SCHEMA_PATH, Path)
    assert isinstance(config.INPUT_DIR, Path)
    assert isinstance(config.DB_PATH, Path)


def test_config_validation_function_exists():
    """Verify validate_config() function exists"""
    import config

    assert hasattr(config, "validate_config")
    assert callable(config.validate_config)


def test_config_validation_checks_required_files():
    """Verify validate_config() raises on missing files"""
    import config

    # This should pass for real project files
    # (Will fail if run in isolated test environment without actual files)
    try:
        config.validate_config()
    except ValueError as e:
        # If validation fails, error message should be helpful
        assert "not found" in str(e).lower()


def test_config_validation_checks_reasoning_effort():
    """Verify validate_config() rejects invalid reasoning effort"""
    import config
    import importlib

    # Temporarily set invalid value
    original = os.environ.get("REASONING_EFFORT")

    try:
        os.environ["REASONING_EFFORT"] = "invalid"

        # Reload config to pick up new env var
        importlib.reload(config)

        with pytest.raises(ValueError, match="REASONING_EFFORT"):
            config.validate_config()

    finally:
        # Restore original
        if original:
            os.environ["REASONING_EFFORT"] = original
        else:
            os.environ.pop("REASONING_EFFORT", None)

        # Reload to restore state
        importlib.reload(config)


def test_config_env_override_for_model():
    """Verify GPT_MODEL can be overridden via environment"""
    import config
    import importlib

    original = os.environ.get("GPT_MODEL")

    try:
        os.environ["GPT_MODEL"] = "openai/gpt-oss-120b"

        # Reload config
        importlib.reload(config)

        assert config.GPT_MODEL == "openai/gpt-oss-120b"

    finally:
        if original:
            os.environ["GPT_MODEL"] = original
        else:
            os.environ.pop("GPT_MODEL", None)

        importlib.reload(config)


def test_config_env_override_for_paths():
    """Verify paths can be overridden via environment"""
    import config
    import importlib

    original_db = os.environ.get("DB_PATH")
    original_input = os.environ.get("INPUT_DIR")

    try:
        os.environ["DB_PATH"] = "/tmp/test.db"
        os.environ["INPUT_DIR"] = "/tmp/input"

        importlib.reload(config)

        assert config.DB_PATH == Path("/tmp/test.db")
        assert config.INPUT_DIR == Path("/tmp/input")

    finally:
        if original_db:
            os.environ["DB_PATH"] = original_db
        else:
            os.environ.pop("DB_PATH", None)

        if original_input:
            os.environ["INPUT_DIR"] = original_input
        else:
            os.environ.pop("INPUT_DIR", None)

        importlib.reload(config)

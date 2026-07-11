"""Unit tests for llm_discovery.model_profiles.resolve_profile.

Each model family (qwen3, gemma4, gpt-oss) has distinct sampling knobs that
must be surfaced in the chat completion request body. resolve_profile maps
a HuggingFace model identifier to the body fragment build_request_body
should merge.
"""

import pytest

from llm_discovery.model_profiles import ModelProfile, resolve_profile


class TestResolveProfile:
    def test_qwen3_6_35b_profile(self):
        p = resolve_profile("Qwen/Qwen3.6-35B-A3B")
        assert isinstance(p, ModelProfile)
        assert p.name == "qwen3"
        assert p.body["temperature"] == 0.0
        assert p.body["max_tokens"] == 32000
        assert p.body["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False

    def test_qwen3_5_still_matches_qwen3_profile(self):
        """Qwen3.5 uses the same thinking-toggle contract as Qwen3.6."""
        p = resolve_profile("Qwen/Qwen3.5-27B")
        assert p.name == "qwen3"

    def test_gemma4_31b_profile(self):
        p = resolve_profile("google/gemma-4-31B-it")
        assert p.name == "gemma4"
        assert p.body["temperature"] == 0.0
        assert p.body["max_tokens"] == 32000
        # Gemma 4 thinking is controlled by <|think|> in system prompt,
        # not by a request-body flag — so extra_body stays empty.
        assert "extra_body" not in p.body

    def test_gemma4_e4b_matches_31b_profile(self):
        assert resolve_profile("google/gemma-4-E4B-it").name == "gemma4"

    def test_gpt_oss_120b_profile(self):
        p = resolve_profile("openai/gpt-oss-120b")
        assert p.name == "gpt-oss"
        assert p.body["temperature"] == 0.0
        assert p.body["extra_body"]["reasoning_effort"] == "low"

    def test_gpt_oss_20b_matches_120b_profile(self):
        assert resolve_profile("openai/gpt-oss-20b").name == "gpt-oss"

    def test_unknown_model_raises_valueerror(self):
        with pytest.raises(ValueError, match="No sampling profile"):
            resolve_profile("meta-llama/Llama-3.1-70B-Instruct")

    def test_empty_model_raises(self):
        with pytest.raises(ValueError, match="No sampling profile"):
            resolve_profile("")

"""Per-model-family sampling profiles for the chat completion request body.

Different model families expose reasoning and generation knobs differently:
  - Qwen3 toggles thinking via ``chat_template_kwargs.enable_thinking``
  - Gemma 4 toggles thinking via presence of ``<|think|>`` in the system prompt
  - gpt-oss takes a ``reasoning_effort`` field (low/medium/high)

build_request_body() consults resolve_profile() to merge the right knobs into
each request rather than hard-coding one-size-fits-all sampling.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelProfile:
    """Request-body fragment for a model family."""

    name: str
    body: dict[str, Any]


_QWEN3 = ModelProfile(
    name="qwen3",
    body={
        "temperature": 0.0,
        "max_tokens": 32000,
        "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
    },
)

_GEMMA4 = ModelProfile(
    name="gemma4",
    body={
        "temperature": 0.0,
        "max_tokens": 32000,
    },
)

_GPT_OSS = ModelProfile(
    name="gpt-oss",
    body={
        "temperature": 0.0,
        "max_tokens": 32000,
        "extra_body": {"reasoning_effort": "low"},
    },
)


def resolve_profile(model_name: str) -> ModelProfile:
    """Return the sampling profile for a HuggingFace model identifier.

    Raises ValueError for unknown model families — classification quality
    depends on model-specific knobs, so silent fallback is worse than loud
    failure.
    """
    if model_name.startswith("Qwen/Qwen3"):
        return _QWEN3
    if model_name.startswith("google/gemma-4"):
        return _GEMMA4
    if model_name.startswith("openai/gpt-oss"):
        return _GPT_OSS
    raise ValueError(
        f"No sampling profile registered for model '{model_name}'. "
        "Add one in src/llm_discovery/model_profiles.py."
    )

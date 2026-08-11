"""
test_language_provider_factory.py

Purpose
-------
Verifies `create_llm_client()` selects the correct concrete `LLMClient`
implementation for each supported `LLMRuntimeConfig.provider` value,
and fails loudly (as a non-retryable `ConfigurationError`) for an
unrecognized provider name -- see `provider_factory.py`'s docstring
for why silent fallback would be worse than a loud failure here.
"""

from __future__ import annotations

import pytest

from language.config import LLMRuntimeConfig
from language.exceptions import ConfigurationError
from language.gemini_client import GeminiLLMClient
from language.llm_client import OpenAICompatibleLLMClient
from language.provider_factory import create_llm_client


def _config(provider: str) -> LLMRuntimeConfig:
    return LLMRuntimeConfig(
        provider=provider,
        model="some-model",
        base_url="https://example.invalid",
        api_key_env_var="SOME_API_KEY",
        timeout_seconds=1.0,
        max_retries=0,
    )


def test_openai_provider_returns_openai_client() -> None:
    client = create_llm_client(_config("openai"))
    assert isinstance(client, OpenAICompatibleLLMClient)


def test_gemini_provider_returns_gemini_client() -> None:
    client = create_llm_client(_config("gemini"))
    assert isinstance(client, GeminiLLMClient)


def test_qwen_provider_returns_openai_compatible_client() -> None:
    # Local/self-hosted Qwen (vLLM/Ollama, ...) speaks the same
    # OpenAI-compatible contract -- no dedicated client class needed.
    client = create_llm_client(_config("qwen"))
    assert isinstance(client, OpenAICompatibleLLMClient)


def test_unsupported_provider_raises_configuration_error() -> None:
    with pytest.raises(ConfigurationError):
        create_llm_client(_config("anthropic"))

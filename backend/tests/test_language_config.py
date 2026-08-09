"""
test_language_config.py

Purpose
-------
Verifies `language.config`'s environment-driven configuration loading:
that sensible defaults apply when no environment variables are set,
that explicit overrides are respected, and that a malformed numeric
environment variable fails as a `ConfigurationError` rather than an
unguarded `ValueError` -- see `config.py`'s `_parse_float_env`/
`_parse_int_env` for the behavior under test.

Why this matters for the rest of `backend/language/`
----------------------------------------------------------
`LanguageAgent.from_config()` and every test of `OpenAICompatibleLLMClient`
depend on `LLMRuntimeConfig`/`PromptAssetPaths` resolving correctly.
A silent misparse here (e.g. a bad timeout value being coerced to `0`
instead of raising) would surface as a confusing failure two layers
away instead of at the actual point of misconfiguration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from language.config import (
    LanguageRuntimeConfig,
    LLMRuntimeConfig,
    PromptAssetPaths,
    RecoveryConfig,
)
from language.exceptions import ConfigurationError


class TestLLMRuntimeConfigDefaults:
    def test_defaults_match_documented_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Ensure a clean environment so this test is not accidentally
        # influenced by variables set outside the test process.
        for name in (
            "LANGUAGE_LLM_PROVIDER",
            "LANGUAGE_LLM_MODEL",
            "LANGUAGE_LLM_BASE_URL",
            "LANGUAGE_LLM_API_KEY_ENV_VAR",
            "LANGUAGE_LLM_TIMEOUT_SECONDS",
            "LANGUAGE_LLM_MAX_RETRIES",
        ):
            monkeypatch.delenv(name, raising=False)

        config = LLMRuntimeConfig.from_env()

        # Defaults point at OpenAI's public API, matching
        # prompt_config.yaml's recommended default provider for
        # strict_json_mode.
        assert config.provider == "openai"
        assert config.model == "gpt-4o-mini"
        assert config.base_url == "https://api.openai.com/v1"
        assert config.api_key_env_var == "OPENAI_API_KEY"
        assert config.timeout_seconds == 30.0
        assert config.max_retries == 2

    def test_explicit_overrides_are_respected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LANGUAGE_LLM_PROVIDER", "qwen")
        monkeypatch.setenv("LANGUAGE_LLM_MODEL", "qwen2.5-72b-instruct")
        monkeypatch.setenv("LANGUAGE_LLM_BASE_URL", "http://localhost:8000/v1")
        monkeypatch.setenv("LANGUAGE_LLM_API_KEY_ENV_VAR", "QWEN_API_KEY")
        monkeypatch.setenv("LANGUAGE_LLM_TIMEOUT_SECONDS", "5.5")
        monkeypatch.setenv("LANGUAGE_LLM_MAX_RETRIES", "0")

        config = LLMRuntimeConfig.from_env()

        assert config.provider == "qwen"
        assert config.model == "qwen2.5-72b-instruct"
        assert config.base_url == "http://localhost:8000/v1"
        assert config.api_key_env_var == "QWEN_API_KEY"
        assert config.timeout_seconds == 5.5
        assert config.max_retries == 0

    def test_invalid_timeout_raises_configuration_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LANGUAGE_LLM_TIMEOUT_SECONDS", "not-a-number")
        with pytest.raises(ConfigurationError):
            LLMRuntimeConfig.from_env()

    def test_invalid_max_retries_raises_configuration_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LANGUAGE_LLM_MAX_RETRIES", "not-an-int")
        with pytest.raises(ConfigurationError):
            LLMRuntimeConfig.from_env()


class TestLLMRuntimeConfigGeminiProvider:
    def test_gemini_provider_selects_gemini_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in (
            "LANGUAGE_LLM_MODEL",
            "LANGUAGE_LLM_BASE_URL",
            "LANGUAGE_LLM_API_KEY_ENV_VAR",
        ):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("LANGUAGE_LLM_PROVIDER", "gemini")

        config = LLMRuntimeConfig.from_env()

        assert config.provider == "gemini"
        assert config.model == "gemini-flash-latest"
        assert config.base_url == "https://generativelanguage.googleapis.com/v1beta"
        assert config.api_key_env_var == "GEMINI_API_KEY"

    def test_gemini_provider_still_allows_explicit_overrides(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LANGUAGE_LLM_PROVIDER", "gemini")
        monkeypatch.setenv("LANGUAGE_LLM_MODEL", "gemini-2.0-flash")
        monkeypatch.setenv("LANGUAGE_LLM_BASE_URL", "http://localhost:9000/v1beta")
        monkeypatch.setenv("LANGUAGE_LLM_API_KEY_ENV_VAR", "MY_GEMINI_KEY")

        config = LLMRuntimeConfig.from_env()

        assert config.model == "gemini-2.0-flash"
        assert config.base_url == "http://localhost:9000/v1beta"
        assert config.api_key_env_var == "MY_GEMINI_KEY"

    def test_openai_defaults_unaffected_when_provider_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Backward compatibility: not setting LANGUAGE_LLM_PROVIDER at
        # all must reproduce Phase 3.4's exact defaults.
        for name in (
            "LANGUAGE_LLM_PROVIDER",
            "LANGUAGE_LLM_MODEL",
            "LANGUAGE_LLM_BASE_URL",
            "LANGUAGE_LLM_API_KEY_ENV_VAR",
        ):
            monkeypatch.delenv(name, raising=False)

        config = LLMRuntimeConfig.from_env()

        assert config.provider == "openai"
        assert config.model == "gpt-4o-mini"
        assert config.base_url == "https://api.openai.com/v1"
        assert config.api_key_env_var == "OPENAI_API_KEY"


class TestRecoveryConfig:
    def test_default_max_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LANGUAGE_RUNTIME_MAX_RETRIES", raising=False)
        config = RecoveryConfig.from_env()
        assert config.max_retries == 2

    def test_explicit_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LANGUAGE_RUNTIME_MAX_RETRIES", "5")
        config = RecoveryConfig.from_env()
        assert config.max_retries == 5

    def test_invalid_value_raises_configuration_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LANGUAGE_RUNTIME_MAX_RETRIES", "not-an-int")
        with pytest.raises(ConfigurationError):
            RecoveryConfig.from_env()


class TestPromptAssetPaths:
    def test_defaults_point_at_repository_prompt_assets(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for name in (
            "LANGUAGE_PARSER_PROMPT_PATH",
            "LANGUAGE_PROMPT_CONFIG_PATH",
            "LANGUAGE_FEWSHOT_EXAMPLES_PATH",
            "LANGUAGE_FEWSHOT_EXAMPLE_COUNT",
        ):
            monkeypatch.delenv(name, raising=False)

        paths = PromptAssetPaths.from_env()

        assert paths.parser_prompt_path.name == "parser_prompt.txt"
        assert paths.prompt_config_path.name == "prompt_config.yaml"
        # Few-shot injection is opt-in only -- see this repository's
        # instruction to never treat benchmark datasets as runtime
        # prompt assets unless explicitly configured.
        assert paths.few_shot_examples_path is None
        assert paths.few_shot_example_count == 3

    def test_fewshot_path_activates_only_when_set(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        examples_file = tmp_path / "examples.json"
        monkeypatch.setenv("LANGUAGE_FEWSHOT_EXAMPLES_PATH", str(examples_file))
        monkeypatch.setenv("LANGUAGE_FEWSHOT_EXAMPLE_COUNT", "5")

        paths = PromptAssetPaths.from_env()

        assert paths.few_shot_examples_path == examples_file
        assert paths.few_shot_example_count == 5


class TestLanguageRuntimeConfig:
    def test_from_env_aggregates_both_sub_configs(self) -> None:
        config = LanguageRuntimeConfig.from_env()
        assert isinstance(config.llm, LLMRuntimeConfig)
        assert isinstance(config.prompts, PromptAssetPaths)
        assert isinstance(config.recovery, RecoveryConfig)

"""
config.py

Purpose
-------
Owns *runtime/deployment* configuration for the Language Parsing
Runtime (Phase 3.4) -- which LLM provider and model to call, where its
credentials live, how long to wait, and how many times to retry a
transient network failure. This is deliberately environment-driven
(never hardcoded, never committed) so the same code can run against a
developer's laptop, a CI job (with the LLM mocked -- see
`backend/tests/`), and a future deployment target
(`deployment/README.md`) without a code change.

Why this is a *separate* concern from `prompt_config.yaml`
--------------------------------------------------------------
`backend/prompts/prompt_config.yaml` (Phase 3.3) already owns every
parameter that describes *how to decode with a specific prompt
version* -- temperature, top_p, max_tokens, strict-JSON-mode
preference, and the schema-validation retry count Phase 3.5 will use.
Duplicating those values here would create two sources of truth that
could silently drift (e.g. this file says `max_tokens: 2048` while
`prompt_config.yaml` says `1024`, and nothing would catch the
disagreement). This file therefore holds only the *path* to
`prompt_config.yaml` (so `PromptBuilder` knows where to find it) plus
settings that have no home in that file because they are about
*deployment*, not about *the prompt*: which provider/model/base URL to
call, which environment variable holds the API key, and how long to
wait on the network. `PromptBuilder` (`prompt_builder.py`) is the only
component that actually reads `prompt_config.yaml`'s contents.

Which component depends on this file
---------------------------------------
`LanguageAgent.from_config()` (`agent.py`) is the intended entry point
that reads `LanguageRuntimeConfig.from_env()` once at construction time
and wires it into a concrete `LLMClient` and `PromptBuilder`. Neither
`LanguageAgent` itself nor any component beyond `llm_client.py` and
`prompt_builder.py` needs to know these values exist -- see each
file's own docstring for why that separation matters.

Security note
---------------
`LLMRuntimeConfig` stores the *name* of the environment variable that
holds the API key (`api_key_env_var`), never the key's value. The key
itself is resolved from `os.environ` at call time, inside
`llm_client.py`, immediately before use -- keeping it out of this
(otherwise freely loggable/repr-able) configuration object entirely.
See `llm_client.py`'s module docstring for the rest of the credential
handling policy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from language.exceptions import ConfigurationError

# ---------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------
# backend/language/config.py -> parent is backend/language/, parent's
# parent is backend/ -- mirrors the pattern already established in
# `backend/config/model_config.py` (REPO_ROOT via `.resolve().parents`)
# so prompt asset paths are correct regardless of the process's current
# working directory, while everything in this project is still *run*
# with `backend/` as the working directory (see
# `backend/tests/test_task.py`'s docstring for that convention).
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_PROMPTS_DIR = _BACKEND_DIR / "prompts"
_DEFAULT_PARSER_PROMPT_PATH = _DEFAULT_PROMPTS_DIR / "parser_prompt.txt"
_DEFAULT_PROMPT_CONFIG_PATH = _DEFAULT_PROMPTS_DIR / "prompt_config.yaml"


def _parse_float_env(name: str, default: float) -> float:
    """
    Reads a float-valued environment variable, falling back to
    `default` when unset. Raises `ConfigurationError` (rather than
    letting a bare `ValueError` propagate) when the variable is set
    but not parseable -- a misconfigured deployment should fail with a
    message that names the offending variable, not a generic Python
    traceback.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"Environment variable {name!r} must be a number, got {raw!r}."
        ) from exc


def _parse_int_env(name: str, default: int) -> int:
    """Integer counterpart to `_parse_float_env` -- see its docstring."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"Environment variable {name!r} must be an integer, got {raw!r}."
        ) from exc


@dataclass(frozen=True)
class LLMRuntimeConfig:
    """
    Deployment-level settings for talking to an LLM provider.

    Deliberately a frozen dataclass (matches `ModelConfig` in
    `backend/config/model_config.py`): immutable so a config object
    handed to an `LLMClient` cannot be mutated out from under it
    mid-request, and a plain typed shape rather than a dict so a typo
    in a field name fails fast (`AttributeError`) instead of silently
    returning `None`.

    Provider-agnostic by construction: `provider` and `model` are
    plain strings, not a closed enum, so adding support for a new
    OpenAI-API-compatible provider (self-hosted Qwen/Llama/Phi via
    vLLM or a similar server -- see
    `backend/prompts/prompt_config.yaml`'s `model_compatibility` list)
    never requires a code change to this class, only a different value
    for these fields at deploy time.
    """

    #: Human-readable provider identifier for logging/observability
    #: only (e.g. "openai") -- not used to select code paths within
    #: `OpenAICompatibleLLMClient`, which speaks one HTTP contract any
    #: OpenAI-API-compatible provider implements.
    provider: str

    #: Model identifier passed through verbatim to the provider's API
    #: (e.g. "gpt-4o-mini"). See `prompt_config.yaml`'s
    #: `model_compatibility` section for the models this project's
    #: prompt has been designed and reviewed against.
    model: str

    #: Base URL of the provider's OpenAI-compatible chat completions
    #: API. Configurable (not hardcoded to OpenAI's own endpoint) so a
    #: self-hosted, OpenAI-API-compatible server can be targeted
    #: without any code change.
    base_url: str

    #: Name of the environment variable that holds the API key -- not
    #: the key itself. See this module's "Security note" above.
    api_key_env_var: str

    #: Per-request network timeout, in seconds. Exceeding it raises
    #: `LLMTimeoutError` (see `llm_client.py`).
    timeout_seconds: float

    #: Number of additional attempts `LLMClient` makes after a
    #: *transient* network failure (connection reset, DNS hiccup) --
    #: distinct from `prompt_config.yaml`'s `output.max_retries`, which
    #: governs Phase 3.5's schema-validation repair loop, a completely
    #: different failure mode (a response was received but was
    #: invalid, vs. no response was received at all).
    max_retries: int

    @classmethod
    def from_env(cls) -> "LLMRuntimeConfig":
        """
        Builds this config from environment variables. `provider`
        selects between this project's three supported providers
        (`"openai"` -- the default, for backward compatibility with
        every Phase 3.4 deployment -- `"gemini"`, added in Phase 3.5
        (see `gemini_client.py`), or `"qwen"`, a local/self-hosted
        OpenAI-API-compatible server added in Phase 8.5); every other
        field defaults to a value appropriate for *that* provider
        unless explicitly overridden, so setting only
        `LANGUAGE_LLM_PROVIDER=gemini` is enough to switch providers
        without also having to know Gemini's base URL or default
        API-key variable name by heart.
        No default exists for the API key itself -- deliberately: an
        application that runs without ever calling
        `LLMClient.complete()` (every test in this repository) must
        never be blocked from starting just because a key isn't set.
        The key is resolved, and its absence surfaces as a
        `ConfigurationError`, only at the moment a concrete client's
        `complete()` is actually called -- see
        `OpenAICompatibleLLMClient`/`GeminiLLMClient`'s own docstrings.

        Gemini free-tier note: `gemini-flash-latest` is used as the
        default Gemini model specifically because it is an
        alias Google keeps pointed at a current, typically free-tier-
        eligible Flash model, rather than a dated snapshot this project
        would have to keep updating as models are deprecated -- see
        `gemini_client.py`'s module docstring for the full rationale.
        Free-tier quota and model availability are controlled entirely
        by Google's current API policies and the caller's own
        account/project eligibility; this default is a reasonable
        starting point, not a guarantee.
        """
        provider = os.environ.get("LANGUAGE_LLM_PROVIDER", "openai")
        if provider == "gemini":
            default_model = "gemini-flash-latest"
            default_base_url = "https://generativelanguage.googleapis.com/v1beta"
            default_api_key_env_var = "GEMINI_API_KEY"
        elif provider == "qwen":
            # Local/self-hosted Qwen via an OpenAI-API-compatible server
            # (vLLM, Ollama, ...) -- see `provider_factory.py`, which
            # reuses `OpenAICompatibleLLMClient` unchanged for this
            # provider. `localhost:8000/v1` is vLLM's own default
            # OpenAI-compatible endpoint; override with
            # LANGUAGE_LLM_BASE_URL for a different host/port. Many
            # local servers do not enforce the bearer token at all --
            # if so, set QWEN_API_KEY to any placeholder value (e.g.
            # "not-needed"); `_resolve_api_key` still requires *some*
            # value to be set, deliberately (see that method's
            # docstring) so this provider's credential handling stays
            # identical to every other provider's.
            default_model = "qwen2.5-7b-instruct"
            default_base_url = "http://localhost:8000/v1"
            default_api_key_env_var = "QWEN_API_KEY"
        else:
            default_model = "gpt-4o-mini"
            default_base_url = "https://api.openai.com/v1"
            default_api_key_env_var = "OPENAI_API_KEY"

        return cls(
            provider=provider,
            model=os.environ.get("LANGUAGE_LLM_MODEL", default_model),
            base_url=os.environ.get("LANGUAGE_LLM_BASE_URL", default_base_url),
            api_key_env_var=os.environ.get(
                "LANGUAGE_LLM_API_KEY_ENV_VAR", default_api_key_env_var
            ),
            timeout_seconds=_parse_float_env("LANGUAGE_LLM_TIMEOUT_SECONDS", 30.0),
            max_retries=_parse_int_env("LANGUAGE_LLM_MAX_RETRIES", 2),
        )


@dataclass(frozen=True)
class PromptAssetPaths:
    """
    Filesystem locations `PromptBuilder` reads from. Kept as a
    dedicated dataclass (rather than loose arguments to
    `PromptBuilder.__init__`) so `LanguageAgent.from_config()` has one
    object to construct and pass along, and so a future caller can
    override individual paths (e.g. in a test, or to point at a
    modified prompt for A/B evaluation in Phase 3.6) without touching
    `LLMRuntimeConfig`.
    """

    #: `backend/prompts/parser_prompt.txt` -- the Phase 3.3 system
    #: prompt, loaded verbatim. See `PromptBuilder` for why this is
    #: read as data, never inlined into Python.
    parser_prompt_path: Path

    #: `backend/prompts/prompt_config.yaml` -- decoding parameters and
    #: prompt/schema version metadata for the version of
    #: `parser_prompt_path` above.
    prompt_config_path: Path

    #: Optional path to a few-shot example file (shape matching
    #: `datasets/language/prompts/examples.json`). `None` (the
    #: default) means few-shot injection is disabled -- per
    #: `backend/prompts/README.md`, that dataset is research/review
    #: data, not a runtime asset, unless a deployment explicitly opts
    #: in by setting `LANGUAGE_FEWSHOT_EXAMPLES_PATH`.
    few_shot_examples_path: Optional[Path]

    #: How many examples to sample from `few_shot_examples_path` when
    #: it is set. Ignored when `few_shot_examples_path` is `None`.
    few_shot_example_count: int

    @classmethod
    def from_env(cls) -> "PromptAssetPaths":
        """
        Builds this config from environment variables, defaulting to
        this repository's actual Phase 3.3 asset locations. Few-shot
        loading stays opt-in: it activates only when
        `LANGUAGE_FEWSHOT_EXAMPLES_PATH` is explicitly set, never by
        guessing at `datasets/language/prompts/examples.json` on its
        own -- see this class's `few_shot_examples_path` docstring for
        why that default matters.
        """
        few_shot_env = os.environ.get("LANGUAGE_FEWSHOT_EXAMPLES_PATH")
        return cls(
            parser_prompt_path=Path(
                os.environ.get(
                    "LANGUAGE_PARSER_PROMPT_PATH", str(_DEFAULT_PARSER_PROMPT_PATH)
                )
            ),
            prompt_config_path=Path(
                os.environ.get(
                    "LANGUAGE_PROMPT_CONFIG_PATH", str(_DEFAULT_PROMPT_CONFIG_PATH)
                )
            ),
            few_shot_examples_path=Path(few_shot_env) if few_shot_env else None,
            few_shot_example_count=_parse_int_env("LANGUAGE_FEWSHOT_EXAMPLE_COUNT", 3),
        )


@dataclass(frozen=True)
class RecoveryConfig:
    """
    Deployment-level setting for Phase 3.5's `recovery.RetryPolicy` --
    how many additional pipeline attempts `LanguageAgent.from_config()`
    permits after a retryable failure (see `failures.is_retryable`).

    Kept as its own small dataclass, separate from both
    `LLMRuntimeConfig` (network-transport retries, a different failure
    mode -- see `RetryPolicy`'s own docstring) and
    `prompt_config.yaml`'s `output.max_retries` (prompt/schema-asset
    configuration, not deployment configuration -- see `config.py`'s
    module docstring on why those two concerns must not merge). A
    deployment can tune how aggressively the runtime retries without
    touching prompt assets, and vice versa.
    """

    #: Additional attempts after the first, following a retryable
    #: `FailureCategory`. `0` (the default) reproduces Phase 3.4's
    #: exact single-attempt behavior -- see `recovery.py`'s module
    #: docstring.
    max_retries: int

    @classmethod
    def from_env(cls) -> "RecoveryConfig":
        return cls(max_retries=_parse_int_env("LANGUAGE_RUNTIME_MAX_RETRIES", 2))


@dataclass(frozen=True)
class LanguageRuntimeConfig:
    """
    Top-level configuration object for the Language Parsing Runtime --
    everything `LanguageAgent.from_config()` needs to wire up a
    concrete `LLMClient` and `PromptBuilder` in one call. Aggregates
    (rather than merges) `LLMRuntimeConfig` and `PromptAssetPaths`
    precisely to keep "how to call the LLM" and "where the prompt
    assets are" visibly separate, even though both are read from the
    environment together for caller convenience.
    """

    llm: LLMRuntimeConfig
    prompts: PromptAssetPaths
    recovery: RecoveryConfig

    @classmethod
    def from_env(cls) -> "LanguageRuntimeConfig":
        """
        The single intended entry point for production/deployment use:
        `LanguageAgent.from_config(LanguageRuntimeConfig.from_env())`.
        Tests should generally not call this -- they construct
        `LanguageAgent` directly from injected fakes/mocks instead, so
        the test suite never depends on the process environment (see
        `backend/language/`'s test suite for the pattern).
        """
        return cls(
            llm=LLMRuntimeConfig.from_env(),
            prompts=PromptAssetPaths.from_env(),
            recovery=RecoveryConfig.from_env(),
        )

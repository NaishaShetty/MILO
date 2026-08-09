"""
test_language_llm_smoke.py

Purpose
-------
Opt-in, real-network smoke tests against an actual OpenAI or Gemini
API endpoint -- deliberately *not* part of the normal deterministic
unit test suite every other `test_language_*.py` file belongs to (see
this repository's Phase 3.5 "Real API Smoke Tests" requirement: "Do
NOT put real API calls in the normal automated test suite").

How this stays out of CI by default
-----------------------------------------
Every test in this module is skipped unless the environment variable
`RUN_LLM_SMOKE_TESTS=true` is set, and skipped again if the specific
provider's credential is not present -- so `.github/workflows/ci.yml`
(which sets neither) collects this file without ever making a network
call or failing for lack of an API key. This module never fails CI by
omission; it fails only when explicitly asked to run and a real call
did not behave as expected.

How to run these locally
------------------------------
    export RUN_LLM_SMOKE_TESTS=true
    export OPENAI_API_KEY="sk-..."       # for the OpenAI smoke test
    export GEMINI_API_KEY="..."          # for the Gemini smoke test (get
                                          # a free-tier key from Google AI
                                          # Studio -- see README.md)
    cd backend && python -m pytest tests/test_language_llm_smoke.py -v

Neither credential is ever printed by this module -- see each test's
assertions, which check only the *shape* of the result, never log or
assert on the credential value itself.
"""

from __future__ import annotations

import os

import pytest

from language.agent import LanguageAgent
from language.config import (
    LanguageRuntimeConfig,
    LLMRuntimeConfig,
    PromptAssetPaths,
    RecoveryConfig,
)
from schemas.task import SingleTask

_SMOKE_ENABLED = os.environ.get("RUN_LLM_SMOKE_TESTS", "").lower() == "true"

_SKIP_REASON = (
    "Real API smoke tests are opt-in -- set RUN_LLM_SMOKE_TESTS=true "
    "to enable (see this module's docstring)."
)


def _agent_for(provider: str, model: str, api_key_env_var: str) -> LanguageAgent:
    config = LanguageRuntimeConfig(
        llm=LLMRuntimeConfig(
            provider=provider,
            model=model,
            base_url=(
                "https://generativelanguage.googleapis.com/v1beta"
                if provider == "gemini"
                else "https://api.openai.com/v1"
            ),
            api_key_env_var=api_key_env_var,
            timeout_seconds=30.0,
            max_retries=1,
        ),
        prompts=PromptAssetPaths.from_env(),
        recovery=RecoveryConfig(max_retries=1),
    )
    return LanguageAgent.from_config(config)


@pytest.mark.skipif(not _SMOKE_ENABLED, reason=_SKIP_REASON)
@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY is not set.",
)
def test_openai_smoke_parses_a_simple_instruction() -> None:
    agent = _agent_for("openai", "gpt-4o-mini", "OPENAI_API_KEY")
    result = agent.parse("Bring me the red mug from the kitchen counter.")
    assert isinstance(result, SingleTask)
    assert result.goal is not None


@pytest.mark.skipif(not _SMOKE_ENABLED, reason=_SKIP_REASON)
@pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY is not set.",
)
def test_gemini_smoke_parses_a_simple_instruction() -> None:
    agent = _agent_for("gemini", "gemini-flash-latest", "GEMINI_API_KEY")
    result = agent.parse("Bring me the red mug from the kitchen counter.")
    assert isinstance(result, SingleTask)
    assert result.goal is not None

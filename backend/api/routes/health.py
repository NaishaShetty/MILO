"""
health.py (backend/api/routes)

Purpose
-------
A dependency-free liveness check for the FastAPI process. Exists so a
deployment platform (or a developer running `curl`) can confirm the
API process is up without that check itself becoming a source of load,
cost, or flakiness.

Why this never calls the LLM provider
--------------------------------------
A health check that calls Gemini/OpenAI on every hit would (a) cost
money per health check, (b) make liveness depend on a third party's
uptime rather than this process's own, and (c) turn a cheap
load-balancer probe into a slow network round trip. This endpoint
instead reports two independent, purely local facts: whether the
process is alive at all, and whether an LLM provider is *configured*
(an API key/provider name is present) -- never whether that
configuration actually works. Determining "does the provider actually
respond" is exactly what `POST /api/v1/language/parse` already does
for a real instruction.
"""

from __future__ import annotations

import os

from fastapi import APIRouter

from language.config import LLMRuntimeConfig

router = APIRouter()


@router.get(
    "/health",
    summary="Liveness check",
    description="Confirms the API process is running. Does not call the "
    "configured LLM provider -- see this module's docstring.",
)
def health() -> dict:
    # Reuses `LLMRuntimeConfig.from_env()` (Phase 3.4) rather than
    # re-deriving "which env var holds the API key for the configured
    # provider" here -- that mapping already has exactly one owner (see
    # `language/config.py`), and duplicating it would risk silently
    # drifting from it.
    llm_config = LLMRuntimeConfig.from_env()
    return {
        "status": "ok",
        "llm_provider_configured": bool(os.environ.get(llm_config.api_key_env_var)),
    }

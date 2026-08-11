"""
language.py (backend/api/routes)

Purpose
-------
Implements `POST /api/v1/language/parse` -- the one endpoint Phase 3.7
adds. Converts a natural language instruction into a validated
`ParsedInstruction` by calling the existing `LanguageAgent`
(`backend/language/agent.py`) and translating its result (or any
`LanguageRuntimeError`) into an HTTP response. Contains no prompt
construction, no LLM call, no JSON parsing, no schema/semantic
validation, and no retry logic of its own -- every one of those
already has exactly one owner inside `backend/language/`; see
`backend/api/__init__.py`'s module docstring for why duplicating any
of it here would be an architectural regression.

Why clarification is a 200, not an error
-----------------------------------------
`needs_clarification=True` on the returned task is a *successful*
parse in Phase 3.2's schema (see `schemas/task.py`'s `Task` docstring
and `language/agent.py`'s "The parse() contract" section) -- the model
correctly recognized an ambiguous instruction and said so, rather than
guessing. Routing that to an HTTP error status would contradict the
runtime's own contract and would force a frontend to distinguish
"the request itself failed" (a bug, or the LLM/network) from "the
request succeeded and the answer is 'please clarify'" via error
handling, when the latter is normal, expected application behavior.
This module instead sets `status="clarification_required"` on an
otherwise-normal 200 `ParseResponse` -- see this file's `_status_for`.

Error mapping
-------------
`LanguageRuntimeError` (`language/exceptions.py`) is a closed
hierarchy; every member is mapped to exactly one HTTP status and one
stable `category` string below, in `_EXCEPTION_STATUS_MAP`. Anything
*not* in that hierarchy (a bug in this API layer itself) is caught by
FastAPI's catch-all handler (`api/app.py`) and reported as a generic
`internal_error` -- this module never re-raises a bare exception with
its original `str()` to the client, since collaborator exception text
could (in principle, for a future collaborator) include request/response
detail that should stay server-side; see `exceptions.py`'s and
`failures.py`'s own Security notes for what is already guaranteed safe
today.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from api.models.language import ParseDiagnostics, ParseRequest, ParseResponse
from language.agent import LanguageAgent
from language.exceptions import (
    ConfigurationError,
    LanguageRuntimeError,
    LLMProviderError,
    LLMTimeoutError,
    PromptLoadError,
    ResponseParsingError,
    RetryExhaustedError,
    SemanticValidationError,
    TaskValidationError,
)
from language.failures import FailureCategory
from schemas.task import ParsedInstruction

logger = logging.getLogger(__name__)

router = APIRouter()


class LanguageStatusResponse(BaseModel):
    """Response body for `GET /language` -- real, current LLM provider
    configuration (Phase 8.5). Never includes the API key itself: only
    the *name* of the environment variable it would live in is ever
    known to `LLMRuntimeConfig` in the first place (see
    `language/config.py`'s Security note), and this endpoint only
    reports whether that variable is currently set, not its value."""

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    configured: bool
    available: bool


@router.get(
    "",
    summary="Real LLM provider configuration status",
    description=(
        "Never 503s -- reports the currently configured provider/model "
        "and whether an API key is present for it (e.g. for Settings' "
        '"LLM Provider" section), without ever exposing the key '
        "itself. `available` does not make a live call to the "
        "provider (that would be a billable request just to render a "
        "status pill) -- it currently mirrors `configured`."
    ),
)
def get_language_status(request: Request) -> LanguageStatusResponse:
    config = request.app.state.language_config.llm
    configured = bool(os.environ.get(config.api_key_env_var))
    return LanguageStatusResponse(
        provider=config.provider,
        model=config.model,
        configured=configured,
        available=configured,
    )


def get_language_agent(request: Request) -> LanguageAgent:
    """
    FastAPI dependency returning the single `LanguageAgent` constructed
    at application startup (`api/app.py`'s `_lifespan`). A dependency
    function (rather than importing a module-level global directly)
    keeps this route trivially testable: `backend/tests/test_api_language.py`
    overrides this exact callable via `app.dependency_overrides` to
    inject a fake `LanguageAgent`, with zero network access and zero
    monkeypatching of internals.
    """
    return request.app.state.language_agent


# Maps each concrete `LanguageRuntimeError` subclass to the (status
# code, category string) an API client should see. Order matters:
# `LLMTimeoutError` is checked before `LLMProviderError` since it is a
# subclass of it (see `exceptions.py`) and Python's `isinstance` would
# otherwise match the parent first if the parent were checked first.
_EXCEPTION_STATUS_MAP: tuple = (
    (LLMTimeoutError, 504, "timeout"),
    (LLMProviderError, 503, "provider_unavailable"),
    (ConfigurationError, 503, "configuration_error"),
    (PromptLoadError, 500, "internal_error"),
    (SemanticValidationError, 502, "upstream_invalid_response"),
    (TaskValidationError, 502, "upstream_invalid_response"),
    (ResponseParsingError, 502, "upstream_invalid_response"),
)

# `FailureCategory` values that indicate the *last* failure before
# `RetryExhaustedError` was a timeout/provider/configuration problem
# rather than a malformed-response problem -- used so an exhausted
# retry loop reports the same category/status a single unretried
# failure of that kind would have, rather than a generic 502.
_RETRY_EXHAUSTED_OVERRIDES: dict = {
    FailureCategory.LLM_TIMEOUT: (504, "timeout"),
    FailureCategory.LLM_PROVIDER_ERROR: (503, "provider_unavailable"),
}


# One safe, generic message per category -- deliberately never the
# original exception's `str()`. See this module's docstring's "Error
# mapping" section for why.
_SAFE_MESSAGES: dict = {
    "timeout": "The language service did not respond in time. Please try again.",
    "provider_unavailable": (
        "The language service is temporarily unavailable. Please try again."
    ),
    "configuration_error": (
        "The language service is not configured correctly. Please contact "
        "the deployment operator."
    ),
    "internal_error": "An unexpected error occurred while processing the instruction.",
    "upstream_invalid_response": (
        "The language service could not produce a valid result for this "
        "instruction. Please try rephrasing it."
    ),
}


def _map_language_runtime_error(exc: LanguageRuntimeError) -> HTTPException:
    """
    Translates one `LanguageRuntimeError` into the `HTTPException` this
    route raises. Kept as a pure function (input exception -> output
    HTTPException) so the mapping itself is unit-testable without
    spinning up a full request.
    """
    if isinstance(exc, RetryExhaustedError):
        last = exc.last_failure
        status_code, category = _RETRY_EXHAUSTED_OVERRIDES.get(
            last.category if last else None, (502, "upstream_invalid_response")
        )
        message = (
            _SAFE_MESSAGES[category]
            if category in _SAFE_MESSAGES
            else (
                "The language service could not produce a valid result after "
                "multiple attempts. Please try rephrasing the instruction."
            )
        )
        return HTTPException(
            status_code=status_code, detail={"category": category, "message": message}
        )

    for exc_type, status_code, category in _EXCEPTION_STATUS_MAP:
        if isinstance(exc, exc_type):
            message = _SAFE_MESSAGES[category]
            return HTTPException(
                status_code=status_code,
                detail={"category": category, "message": message},
            )

    # Defensive fallback: a `LanguageRuntimeError` subclass added to
    # `exceptions.py` in the future without a matching entry above.
    # Never reached by any exception type that exists today.
    return HTTPException(
        status_code=500,
        detail={
            "category": "internal_error",
            "message": "An unexpected error occurred while processing the instruction.",
        },
    )


def _status_for(instruction: ParsedInstruction) -> str:
    """
    `"clarification_required"` mirrors the *top-level* task's own
    `needs_clarification` flag; a `MultiTask` is only flagged this way
    if the `MultiTask` itself (not merely one of its `subtasks`) was
    marked ambiguous by the model -- consistent with how
    `needs_clarification` is defined per-`Task` in `schemas/task.py`.
    """
    return "clarification_required" if instruction.needs_clarification else "ok"


@router.post(
    "/parse",
    response_model=ParseResponse,
    summary="Parse a natural language instruction",
    description=(
        "Converts a natural language instruction into a validated "
        "ParsedInstruction (SingleTask or MultiTask) using the existing "
        "Language Understanding runtime (PromptBuilder, LLMClient, "
        "ResponseParser, Recovery, SchemaValidator). This endpoint does "
        "NOT execute robot actions, plan, or interact with the simulator "
        "-- its output is the final ParsedInstruction, nothing more."
    ),
    responses={
        422: {
            "description": "Invalid request body (empty/whitespace-only instruction, etc.)"
        },
        502: {
            "description": "The LLM provider returned a response that could not be "
            "validated as a task, even after recovery."
        },
        503: {
            "description": "The LLM provider or language service is unavailable/misconfigured."
        },
        504: {"description": "The LLM provider did not respond in time."},
        500: {"description": "An unexpected internal error occurred."},
    },
)
def parse_instruction(
    body: ParseRequest,
    agent: LanguageAgent = Depends(get_language_agent),
) -> ParseResponse:
    try:
        outcome = agent.parse_with_diagnostics(body.instruction)
    except LanguageRuntimeError as exc:
        # Every individual failure has already been logged by the
        # runtime itself (see `language/agent.py`'s
        # `parse_with_diagnostics`); this line only records that the
        # HTTP layer observed and mapped it, without duplicating the
        # instruction text or exception internals in the log.
        logger.warning(
            "language_api.parse.failed",
            extra={"exception_type": type(exc).__name__},
        )
        raise _map_language_runtime_error(exc) from None

    return ParseResponse(
        status=_status_for(outcome.instruction),
        result=outcome.instruction,
        diagnostics=ParseDiagnostics(
            provider=outcome.metadata.provider,
            model=outcome.metadata.model,
            prompt_version=outcome.metadata.prompt_version,
            schema_version=outcome.metadata.schema_version,
            attempt_count=outcome.metadata.attempt_number,
            latency_ms=outcome.metadata.latency_ms,
            recovered=outcome.metadata.recovered,
        ),
    )

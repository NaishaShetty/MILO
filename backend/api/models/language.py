"""
language.py (backend/api/models)

Purpose
-------
Defines the request/response envelope for `POST /api/v1/language/parse`
-- the only new "shape" this API introduces. The task data itself is
never redefined here: `ParseResponse.result` is typed as the real
`backend.schemas.task.ParsedInstruction` discriminated union, so
FastAPI's OpenAPI schema and the actual JSON returned to a client are
always the authoritative Phase 3.2 schema, never a hand-maintained
copy that could drift from it (see this repository's Phase 3.7
requirement: "Do not manually reconstruct the task fields. Serialize
the actual validated Phase 3.2 Pydantic model.").

Which component depends on this file
-------------------------------------
`backend/api/routes/language.py` is the only consumer: it validates
incoming requests against `ParseRequest` and constructs `ParseResponse`
from a `LanguageAgent.parse_with_diagnostics()` result.

Security note
-------------
`ParseDiagnostics` intentionally exposes only the fields already
proven safe by `backend/language/failures.py`'s `RuntimeMetadata`
(provider name, model name, prompt/schema version, attempt count,
latency, whether recovery fired) -- never a credential, header, or raw
provider error body. See that module's own Security note for why
`RuntimeMetadata` can never carry one in the first place.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.task import ParsedInstruction


class ParseRequest(BaseModel):
    """
    Request body for `POST /api/v1/language/parse`.

    Deliberately the *only* validation performed before the instruction
    reaches `LanguageAgent`: "is this a non-empty string within a
    reasonable size". Anything about whether the instruction is
    *understandable* is the Language Understanding subsystem's job, not
    this model's -- see this package's module docstring on the
    architectural boundary this API must not cross.
    """

    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(
        min_length=1,
        max_length=2000,
        description="Raw natural language instruction to parse, e.g. "
        "'Bring me the red mug.'. Must not be empty or whitespace-only.",
        examples=["Bring me the red mug."],
    )

    @field_validator("instruction", mode="after")
    @classmethod
    def _reject_whitespace_only(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("instruction must not be empty or whitespace-only")
        return stripped


class ParseDiagnostics(BaseModel):
    """
    Safe, credential-free observability data about how a parse result
    was obtained -- a direct, field-for-field mirror of
    `backend.language.failures.RuntimeMetadata`. Never includes an API
    key, auth header, or raw provider response body; see this module's
    Security note.
    """

    provider: Optional[str] = Field(
        default=None, description="LLM provider identifier, e.g. 'gemini' or 'openai'."
    )
    model: Optional[str] = Field(
        default=None, description="Model identifier used for the successful attempt."
    )
    prompt_version: Optional[str] = Field(
        default=None, description="Version of parser_prompt.txt used for this request."
    )
    schema_version: Optional[str] = Field(
        default=None,
        description="Version of the ParsedInstruction schema validated against.",
    )
    attempt_count: int = Field(
        description="1-indexed number of LLM calls made to produce this result."
    )
    latency_ms: Optional[float] = Field(
        default=None,
        description="Wall-clock latency of the successful LLM call, in ms.",
    )
    recovered: bool = Field(
        description="True if at least one earlier attempt failed before this "
        "result was obtained."
    )


class ParseResponse(BaseModel):
    """
    Successful response body for `POST /api/v1/language/parse`.

    `status` distinguishes an unambiguous parse from one the model
    flagged as needing clarification -- both are HTTP 200 (see this
    package's module docstring and `routes/language.py`'s docstring on
    why clarification is not an error).
    """

    status: str = Field(
        description="'ok' for an unambiguous parse, 'clarification_required' "
        "when the parsed task's needs_clarification field is true.",
        examples=["ok"],
    )
    result: ParsedInstruction = Field(
        description="The validated SingleTask or MultiTask produced by the "
        "Language Understanding runtime, serialized exactly as validated -- "
        "not reconstructed by this API layer."
    )
    diagnostics: Optional[ParseDiagnostics] = Field(
        default=None,
        description="Safe operational metadata about this parse. Present "
        "whenever the underlying runtime call succeeded.",
    )


class ErrorResponse(BaseModel):
    """
    Documented shape of every non-2xx response this API returns.
    Exists purely for OpenAPI documentation and client-side
    type-safety; the actual instance is constructed by
    `routes/language.py`'s error mapper via `HTTPException(detail=...)`.

    `category` is a stable machine-readable string (independent of the
    HTTP status code) a frontend can switch on without parsing
    `message` text -- see `routes/language.py` for the closed set of
    values this field takes.
    """

    category: str = Field(
        description="Machine-readable failure category, e.g. "
        "'invalid_request', 'provider_unavailable', 'timeout', 'internal_error'.",
        examples=["provider_unavailable"],
    )
    message: str = Field(
        description="Human-readable, credential-free description of what "
        "went wrong. Never contains a stack trace, API key, or raw provider "
        "error body.",
        examples=["The language service is temporarily unavailable. Please try again."],
    )

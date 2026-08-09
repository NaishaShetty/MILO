"""
exceptions.py

Purpose
-------
Defines the complete exception vocabulary for the Language Parsing
Runtime (Phase 3.4) -- the layer that turns a raw natural language
instruction into a validated `SingleTask`/`MultiTask`
(`backend/schemas/task.py`) by coordinating `PromptBuilder`,
`LLMClient`, `ResponseParser`, and `SchemaValidator`.

Why this file exists
----------------------
Every other module in `backend/language/` raises exceptions defined
here instead of letting library exceptions (`requests.RequestException`,
`json.JSONDecodeError`, `pydantic.ValidationError`, bare `OSError`,
...) leak across module boundaries. Without a shared vocabulary, a
caller of `LanguageAgent.parse()` (Phase 4's Planner, Phase 3.7's API
layer, or a test) would need to know which third-party library each
internal component happens to use today just to catch its failures --
and that knowledge would silently break every time an internal
implementation detail changed (e.g. swapping `requests` for `httpx`,
or PyYAML for `ruamel.yaml`). A closed, documented set of exceptions
is the actual contract `LanguageAgent` exposes to its callers; the
underlying library exceptions are an implementation detail that stays
inside `backend/language/`.

Which component depends on this file
---------------------------------------
Every file in `backend/language/` (`config.py`, `prompt_builder.py`,
`llm_client.py`, `response_parser.py`, `schema_validator.py`,
`agent.py`) raises one of these. `LanguageAgent` (`agent.py`) is the
orchestrator all of them funnel through, so its caller only ever needs
to catch `LanguageRuntimeError` (or a specific subclass) -- never a
provider SDK exception, a `json` exception, or a raw `pydantic`
exception.

Why one hierarchy instead of scattered exceptions
----------------------------------------------------
Each subclass below corresponds to exactly one pipeline stage that can
fail (config loading, prompt loading, the LLM call itself, a timeout
specifically, response parsing, schema validation) -- deliberately not
one exception per failure *reason* within a stage, which would produce
an unbounded, hard-to-catch class explosion. A caller that only cares
"did the LLM call fail" catches `LLMProviderError`; a caller that wants
finer-grained handling (e.g. retry timeouts but not hard failures)
catches `LLMTimeoutError` specifically, since it subclasses
`LLMProviderError` and is still caught by the broader handler.
"""

from __future__ import annotations

from typing import List, Optional

from language.failures import FailureRecord


class LanguageRuntimeError(Exception):
    """
    Base class for every exception raised anywhere in
    `backend/language/`.

    Why it exists: lets a caller (Phase 4's Planner, Phase 3.7's future
    API layer, or a test) write a single `except LanguageRuntimeError`
    to catch *any* language-runtime failure without enumerating every
    subclass, while still allowing a more specific `except` clause
    where the caller wants to react differently to, say, a timeout
    versus a validation failure.
    """


class ConfigurationError(LanguageRuntimeError):
    """
    Raised when the runtime cannot be configured correctly before any
    LLM call is attempted -- e.g. a required environment variable
    (such as an API key) is missing, or `prompt_config.yaml` is
    malformed/missing a required key.

    Why this is distinct from `PromptLoadError`/`LLMProviderError`:
    a configuration failure is detectable and fixable *before* any
    network or file I/O is attempted for a specific `parse()` call --
    surfacing it as its own type lets a caller (or a future health
    check) distinguish "this deployment is misconfigured" from "this
    one request failed."
    """


class PromptLoadError(LanguageRuntimeError):
    """
    Raised when `PromptBuilder` cannot load its required assets --
    `backend/prompts/parser_prompt.txt` is missing/unreadable, or
    `backend/prompts/prompt_config.yaml` fails to parse as valid YAML.

    Kept distinct from `ConfigurationError`: a missing prompt file is a
    problem with the *asset package* Phase 3.3 built, not with how the
    runtime layer itself (Phase 3.4) was configured -- the two have
    different owners and different fixes.
    """


class LLMProviderError(LanguageRuntimeError):
    """
    Raised when `LLMClient` fails to obtain a response from the
    configured LLM provider for a reason other than a timeout --
    a non-2xx HTTP status, a network error, a malformed provider
    response envelope, or missing/rejected credentials.

    Security note: any message attached to this exception (or a
    subclass) must never include the API key itself, even indirectly
    via a raw request/response dump -- see `llm_client.py`'s
    `_safe_error_detail` helper, which is the only place error text is
    assembled before being passed here.
    """


class LLMTimeoutError(LLMProviderError):
    """
    Raised when the configured LLM provider does not respond within
    `LLMRuntimeConfig.timeout_seconds`.

    Subclasses `LLMProviderError` rather than `LanguageRuntimeError`
    directly: a timeout *is* a provider failure from the caller's
    perspective (no response was obtained), so any code that already
    catches `LLMProviderError` continues to catch timeouts too. It is
    still its own type because a caller may want to react differently
    to "the network path to the provider is failing" (may be worth an
    automatic retry higher up the stack) versus "the provider actively
    rejected the request" (retrying is unlikely to help).
    """


class ResponseParsingError(LanguageRuntimeError):
    """
    Raised when `ResponseParser` cannot turn the LLM's raw text output
    into a Python `dict` -- empty output, malformed JSON, or a
    top-level JSON value that isn't an object (e.g. a bare string or
    list, which `SchemaValidator` could never validate as a
    `ParsedInstruction` regardless).

    This exception carries no fabricated data: `ResponseParser` never
    invents a "best guess" dict to keep the pipeline moving.
    Constructing one here and letting it propagate is the only correct
    behavior when the model's output cannot be trusted.
    """


class TaskValidationError(LanguageRuntimeError):
    """
    Raised when `SchemaValidator` receives a syntactically valid
    Python object that fails Phase 3.2's `ParsedInstruction` schema
    (`backend/schemas/task.py`) -- a required field is missing, an
    enum value isn't recognized, or a cross-field invariant (e.g.
    `needs_clarification` consistency) is violated.

    Preserves the original `pydantic.ValidationError` as
    `original_error` rather than only stringifying it, so a caller
    that wants structured per-field error detail (e.g. a future API
    layer returning field-level errors to a client) does not need to
    re-parse this exception's message string.
    """

    def __init__(
        self, message: str, *, original_error: Optional[Exception] = None
    ) -> None:
        super().__init__(message)
        # Kept as the original pydantic exception object (not just its
        # `str()`) so `.errors()` -- pydantic's structured, per-field
        # error list -- remains available to any caller that wants it,
        # e.g. Phase 3.5's repair strategy or a future API error
        # response. See SchemaValidator.validate() for where this is
        # populated.
        self.original_error = original_error


class SemanticValidationError(LanguageRuntimeError):
    """
    Raised by `semantic_validator.py` when a `ParsedInstruction` passes
    Phase 3.2's structural schema but does not make sense as a task --
    e.g. a goal that requires an object with none stated, or a task
    whose `object` and `target` are identical (see that module's
    docstring for the full rule set).

    Kept distinct from `TaskValidationError`: a structural failure
    means "this cannot even be parsed as a `SingleTask`/`MultiTask`";
    a semantic failure means "it parsed fine, but the fields it
    contains cannot represent an executable task". `recovery.py` needs
    to tell these apart because they come from different stages and,
    per this project's retry-strategy requirements, may warrant
    different recovery behavior (a fresh generation vs. a targeted
    clarification signal).
    """


class RetryExhaustedError(LanguageRuntimeError):
    """
    Raised by `recovery.py` when every permitted attempt at producing a
    valid `ParsedInstruction` has failed. This is the *only* exception
    `recovery.py` raises once more than one attempt has actually been
    made -- see that module's docstring for why a single-attempt
    (`max_retries=0`) failure instead re-raises the original,
    stage-specific exception unmodified (preserving Phase 3.4's exact
    error-propagation contract when recovery is effectively disabled).

    Carries the full `FailureRecord` history (`self.failures`) rather
    than only the last failure's message, so a caller -- a test, a
    future Phase 3.6 benchmark harness, or a future Phase 3.7 API error
    response -- can inspect exactly which categories were hit and in
    what order, without re-parsing this exception's `str()`.
    """

    def __init__(self, message: str, *, failures: List[FailureRecord]) -> None:
        super().__init__(message)
        self.failures = failures

    @property
    def last_failure(self) -> Optional[FailureRecord]:
        """The most recent recorded failure, or `None` if `failures` is empty."""
        return self.failures[-1] if self.failures else None

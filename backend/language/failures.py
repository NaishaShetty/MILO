"""
failures.py

Purpose
-------
Defines the closed failure taxonomy for the Language Parsing Runtime's
Output Validation & Error Recovery layer (Phase 3.5), plus the
structured, credential-free metadata every failure and every attempt
carries. Before this file existed, "what went wrong" was only
observable as an exception *type* (`language.exceptions`); that is
enough for a caller to `except`, but not enough for a retry policy to
decide "is this worth trying again", or for a future Phase 3.6
benchmark harness to aggregate "how many INVALID_JSON failures did
provider X have at temperature Y". `FailureCategory` is that missing
vocabulary, and `RuntimeMetadata`/`FailureRecord` are the structured
payloads every recovery decision and every log line are built from.

Which components depend on this file
-------------------------------------
`recovery.py` (the retry/repair orchestrator) is the only component
that *decides* things from a `FailureCategory` (via `is_retryable`).
`exceptions.py` imports `FailureCategory`/`FailureRecord` so
`RetryExhaustedError` can carry a structured failure history.
`agent.py` surfaces `RuntimeMetadata` on its `ParseOutcome` so a future
Phase 3.6 harness or Phase 3.7 API layer has provider/model/latency/
retry data without needing to parse a log line.

Why retryability is a property of the category, not of the call site
----------------------------------------------------------------------
If every call site decided independently whether a given failure was
worth retrying, that policy would drift as new call sites were added.
Centralizing it here (`_RETRYABLE_CATEGORIES`) means the retry policy
documented in the project's Phase 3.5 requirements (INVALID_JSON:
retry; LLM_CONFIGURATION_ERROR: fail immediately; ...) is enforced in
exactly one place, and is itself unit-testable independently of
`recovery.py`'s control flow.

Security note
---------------
Nothing in this module ever holds a credential. `FailureRecord.message`
is always a string already produced by an upstream component
(`llm_client.py`'s `_redact`/`_safe_error_detail`, or a Pydantic
`ValidationError`'s own message) -- this module only carries that
string through, it never assembles error text from raw request/response
data itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import FrozenSet, Optional


class FailureCategory(str, Enum):
    """
    Every distinct way a `parse()` attempt can fail to produce a usable
    result, closed and exhaustive (per this repository's "use enums
    rather than scattered magic strings" requirement). Each member maps
    to exactly one pipeline stage or one recognizably distinct failure
    mode within a stage -- see each member's comment for the stage it
    belongs to and, where relevant, why it is split from a neighboring
    category rather than merged with it.
    """

    #: ResponseParser stage: the LLM's raw text did not parse as JSON.
    INVALID_JSON = "invalid_json"
    #: ResponseParser stage: the LLM returned no content at all.
    EMPTY_RESPONSE = "empty_response"
    #: SchemaValidator stage: valid JSON, but it fails Phase 3.2's
    #: `ParsedInstruction` schema (missing field, bad enum, ...).
    SCHEMA_VALIDATION_ERROR = "schema_validation_error"
    #: Semantic validation stage (this phase): structurally valid but
    #: semantically incomplete/contradictory -- see
    #: `semantic_validator.py`.
    SEMANTIC_VALIDATION_ERROR = "semantic_validation_error"
    #: Not a failure of the pipeline -- a *successful* parse in which
    #: the model itself declared `needs_clarification=True`. Kept in
    #: this enum anyway (rather than a separate vocabulary) so
    #: observability/benchmarking can tag a `parse()` outcome with one
    #: consistent field regardless of whether it succeeded cleanly,
    #: succeeded with ambiguity, or failed outright.
    AMBIGUOUS_COMMAND = "ambiguous_command"
    #: LLMClient stage: the provider did not respond within the
    #: configured timeout.
    LLM_TIMEOUT = "llm_timeout"
    #: LLMClient stage: the provider responded, but with an error (bad
    #: status, malformed envelope, network failure after retries).
    LLM_PROVIDER_ERROR = "llm_provider_error"
    #: LLMClient/config stage: the runtime cannot even attempt a call --
    #: missing/invalid credentials, an unsupported provider name, or a
    #: malformed deployment configuration. Deliberately distinct from
    #: `LLM_PROVIDER_ERROR`: a provider error means "we asked and it
    #: failed"; this means "we could not ask at all", which retrying
    #: can never fix.
    LLM_CONFIGURATION_ERROR = "llm_configuration_error"
    #: Recovery stage: every permitted attempt was made and none
    #: succeeded. Terminal -- never itself retried.
    RETRY_EXHAUSTED = "retry_exhausted"
    #: ResponseParser stage: the response was valid JSON but not a JSON
    #: object (e.g. a bare list/string), or otherwise a shape this
    #: runtime has no handling for.
    UNSUPPORTED_RESPONSE = "unsupported_response"
    #: Repair stage: a conservative syntactic repair was attempted (see
    #: `repair.py`) and the result still did not parse/validate.
    SAFE_REPAIR_FAILED = "safe_repair_failed"


# The subset of `FailureCategory` for which re-attempting the same
# instruction against the LLM has a realistic chance of succeeding --
# see this module's docstring and the project's Phase 3.5 "Retry
# Strategy" requirements for the rationale behind each inclusion/
# exclusion below.
#
# Included: transient or model-sampling-variance failures, where a
# fresh generation may simply come out well-formed.
# Excluded: `LLM_CONFIGURATION_ERROR` (retrying an invalid API key
# forever cannot fix it -- fail fast), `RETRY_EXHAUSTED` (terminal by
# definition), `AMBIGUOUS_COMMAND` (not a failure to retry away from --
# see the enum member's own comment), `SAFE_REPAIR_FAILED` (a repair
# already tried and failed; retrying without a fresh LLM call would
# just fail identically).
_RETRYABLE_CATEGORIES: FrozenSet[FailureCategory] = frozenset(
    {
        FailureCategory.INVALID_JSON,
        FailureCategory.EMPTY_RESPONSE,
        FailureCategory.SCHEMA_VALIDATION_ERROR,
        FailureCategory.SEMANTIC_VALIDATION_ERROR,
        FailureCategory.LLM_TIMEOUT,
        FailureCategory.LLM_PROVIDER_ERROR,
        FailureCategory.UNSUPPORTED_RESPONSE,
    }
)


def is_retryable(category: FailureCategory) -> bool:
    """
    Single source of truth for "should `recovery.py` attempt this
    instruction again". See `_RETRYABLE_CATEGORIES` above for the
    membership rationale -- this function exists so no call site ever
    needs to inline that set itself.
    """
    return category in _RETRYABLE_CATEGORIES


@dataclass(frozen=True)
class RuntimeMetadata:
    """
    Structured, credential-free observability data describing one
    `parse()` call's outcome -- provider/model identity, which prompt
    and schema version were used, how many attempts it took, whether a
    retry actually recovered a failure, and how long it took.

    Why this exists
        The Phase 3.5 requirements ask for this data to be available to
        a future Phase 3.6 benchmark harness and Phase 3.7 API layer
        "without exposing sensitive information" and "without
        introducing an unnecessarily complicated observability
        framework" -- a small frozen dataclass satisfies both: it is
        trivially serializable (`dataclasses.asdict`), trivially
        logged via `logging`'s `extra=`, and carries no object with a
        `__repr__` that could ever include a credential.
    """

    provider: Optional[str]
    model: Optional[str]
    prompt_version: Optional[str]
    schema_version: Optional[str]
    #: 1-indexed count of LLM calls actually made for this `parse()`.
    attempt_number: int
    #: Wall-clock time of the LLM call that ultimately produced the
    #: returned result, in milliseconds. `None` if no call succeeded.
    latency_ms: Optional[float]
    #: True when at least one failure (an LLM-call retry, a repaired
    #: response, a schema/semantic retry -- any of them) was recorded
    #: before the attempt that ultimately succeeded -- i.e. the
    #: recovery loop actually salvaged an otherwise-failed `parse()`
    #: call. Kept as an explicit field (rather than making callers
    #: derive it from `attempt_number`, which a same-attempt repair
    #: would not change) since "did recovery help" is exactly the
    #: metric a benchmark harness cares about.
    recovered: bool
    #: The category of the *last* failure encountered before this
    #: outcome, if any -- `None` on a first-attempt clean success.
    #: Present even on success so "succeeded, but only after an
    #: INVALID_JSON failure on attempt 1" is representable.
    last_failure: Optional[FailureCategory] = None


@dataclass(frozen=True)
class FailureRecord:
    """
    One failed attempt within a `parse()` call's recovery loop --
    the unit `recovery.py` accumulates and `RetryExhaustedError`
    (`exceptions.py`) carries as its structured failure history.

    Kept deliberately minimal: a category, which stage produced it, a
    human-readable (already-redacted, per this module's Security note)
    message, whether it was considered retryable, and which attempt
    number it occurred on. Enough for logging, testing, and future
    benchmarking without re-deriving any of it from exception text.
    """

    category: FailureCategory
    stage: str
    message: str
    retryable: bool
    attempt_number: int

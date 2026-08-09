"""
recovery.py

Purpose
-------
Implements the "Recovery / Retry" stage the Phase 3.5 architecture
inserts between `LLMClient`/`ResponseParser`/`SchemaValidator` and the
`ParsedInstruction` `LanguageAgent.parse()` returns. This is the one
component in `backend/language/` allowed to call an LLM more than once
for a single `parse()` invocation, and the one component that knows
which `FailureCategory` (`failures.py`) is worth a fresh attempt versus
a hard stop. Every other component in this package (`llm_client.py`,
`response_parser.py`, `schema_validator.py`, `semantic_validator.py`)
still makes exactly one attempt at its own job and raises on failure,
exactly as in Phase 3.4 -- this module is the only thing that decides
"try again".

Why this lives outside `LanguageAgent`
-------------------------------------------
`agent.py`'s own docstring is explicit that `LanguageAgent` must stay
thin and never absorb a collaborator's responsibility. A retry loop
with per-category policy, repair-attempt logic, and structured failure
accumulation is exactly the kind of "just one small piece" that turns
an orchestrator into an unmaintainable god-object if inlined into
`parse()`. `RecoveryEngine` is `LanguageAgent`'s fifth collaborator,
constructed the same way the other four are (dependency injection, see
`agent.py`), so it is independently testable with fake `LLMClient`/
`ResponseParser`/`SchemaValidator` instances and zero network access,
exactly like every other component in this package.

The one behavior this module is built to preserve exactly
----------------------------------------------------------------
When `RetryPolicy.max_retries == 0` (the default -- see this module's
`RetryPolicy`), exactly one attempt is made, and a failure at any stage
re-raises the *original*, stage-specific exception (`LLMProviderError`,
`ResponseParsingError`, `TaskValidationError`, ...) completely
unmodified -- never wrapped, never replaced. This is what makes
`RecoveryEngine` a strict superset of Phase 3.4's `LanguageAgent.parse()`
behavior rather than a breaking change: a caller that never opts into
retries (every existing Phase 3.4 test, and any production caller that
does not configure `RetryPolicy`) observes identical behavior to before
this file existed. `RetryExhaustedError` is raised only once an actual
retry has happened and still failed -- see `_finalize_failure` below
for exactly where that line is drawn.

Retry policy rationale (Phase 3.5 "Retry Strategy" requirement)
----------------------------------------------------------------------
- INVALID_JSON / EMPTY_RESPONSE / UNSUPPORTED_RESPONSE: retried -- a
  fresh generation may simply come out well-formed; these are sampling
  artifacts, not a structural mismatch between prompt and provider.
- SCHEMA_VALIDATION_ERROR / SEMANTIC_VALIDATION_ERROR: retried -- same
  rationale, though a semantic failure realistically has lower odds of
  self-correcting than a pure formatting slip; still worth one more
  try before surfacing to the caller, per this project's Phase 3.5
  "retry or clarification depending on context" guidance. This module
  does not attempt to invent a clarification response on the model's
  behalf -- if the model itself sets `needs_clarification=True`, that
  is a *successful* parse (see `agent.py`), not a failure this module
  ever sees at all.
- LLM_TIMEOUT / LLM_PROVIDER_ERROR: retried -- transient network/
  provider conditions that a second attempt has a real chance of not
  hitting again.
- LLM_CONFIGURATION_ERROR: never retried. Handled *outside* the normal
  failure-classification path entirely (see `run()` below) -- a
  missing or invalid credential cannot be fixed by calling the same
  broken configuration again, so this fails on the first attempt no
  matter how `RetryPolicy.max_retries` is configured.
- SAFE_REPAIR_FAILED: never retried further -- see `failures.py`'s
  `_RETRYABLE_CATEGORIES` for why a failed repair is treated as
  terminal for the current attempt rather than looped on.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from language.exceptions import (
    ConfigurationError,
    LanguageRuntimeError,
    LLMProviderError,
    LLMTimeoutError,
    ResponseParsingError,
    RetryExhaustedError,
    SemanticValidationError,
    TaskValidationError,
)
from language.failures import (
    FailureCategory,
    FailureRecord,
    RuntimeMetadata,
    is_retryable,
)
from language.llm_client import LLMClient, LLMRequest, LLMResponse
from language.repair import SafeResponseRepairer
from language.response_parser import ResponseParser
from language.schema_validator import SchemaValidator
from language.semantic_validator import SemanticValidator
from schemas.task import ParsedInstruction

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryPolicy:
    """
    How many additional attempts `RecoveryEngine` may make after a
    retryable failure. Defaults to `0` (no retries) deliberately -- see
    this module's docstring for why that default is what keeps
    `RecoveryEngine` behaviorally invisible to any caller that does not
    explicitly opt in.

    Distinct from `LLMRuntimeConfig.max_retries`
    (`language/config.py`), which governs `OpenAICompatibleLLMClient`'s
    *network-transport* retry (a connection reset during one HTTP
    call). This field governs retrying the entire
    prompt -> LLM -> parse -> validate pipeline after a *received but
    unusable* response -- a different failure mode at a different
    layer, matching the distinction `LLMRuntimeConfig.max_retries`'s
    own docstring already draws.
    """

    max_retries: int = 0


@dataclass(frozen=True)
class RecoveryOutcome:
    """
    The successful result of `RecoveryEngine.run()`: a validated
    `ParsedInstruction` plus the `RuntimeMetadata` describing how it was
    obtained. Kept as one object (rather than a tuple) so
    `LanguageAgent` has a single, named thing to unpack -- see
    `agent.py`'s `parse_with_diagnostics`.
    """

    instruction: ParsedInstruction
    metadata: RuntimeMetadata


class RecoveryEngine:
    """
    Owns the bounded attempt loop: call the LLM, parse its response
    (repairing it once if parsing fails), validate it structurally,
    validate it semantically (if a `SemanticValidator` is configured),
    and either return a successful `RecoveryOutcome` or exhaust the
    configured `RetryPolicy` and raise.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        response_parser: ResponseParser,
        schema_validator: SchemaValidator,
        semantic_validator: Optional[SemanticValidator] = None,
        repairer: Optional[SafeResponseRepairer] = None,
        retry_policy: Optional[RetryPolicy] = None,
    ) -> None:
        self._llm_client = llm_client
        self._response_parser = response_parser
        self._schema_validator = schema_validator
        self._semantic_validator = semantic_validator
        self._repairer = repairer or SafeResponseRepairer()
        self._retry_policy = retry_policy or RetryPolicy()

    def run(self, request: LLMRequest) -> RecoveryOutcome:
        """
        Runs the full attempt loop for one already-built `LLMRequest`.
        See this module's docstring for the exact re-raise contract on
        failure.
        """
        total_attempts = self._retry_policy.max_retries + 1
        failures: List[FailureRecord] = []

        for attempt in range(1, total_attempts + 1):
            outcome = self._try_once(request, attempt, total_attempts, failures)
            if outcome is not None:
                return outcome
            # `_try_once` returning `None` means it recorded a
            # retryable failure and there is another attempt left --
            # loop again. A terminal failure raises from inside
            # `_try_once` (or its helpers) instead of returning.

        # Unreachable: `_try_once` always either returns a
        # `RecoveryOutcome` or raises before the loop runs out of
        # attempts on its own. Present only to satisfy static
        # type-checking that every path returns or raises.
        raise AssertionError("unreachable")

    def _try_once(
        self,
        request: LLMRequest,
        attempt: int,
        total_attempts: int,
        failures: List[FailureRecord],
    ) -> Optional[RecoveryOutcome]:
        response = self._call_llm(request, attempt, total_attempts, failures)
        if response is None:
            return None

        data, repaired = self._parse_response(
            response, attempt, total_attempts, failures
        )
        if data is None:
            return None

        instruction = self._validate_schema(data, attempt, total_attempts, failures)
        if instruction is None:
            return None

        if self._semantic_validator is not None:
            ok = self._validate_semantics(
                instruction, attempt, total_attempts, failures
            )
            if not ok:
                return None

        metadata = RuntimeMetadata(
            provider=response.provider,
            model=response.model,
            prompt_version=request.prompt_version,
            schema_version=request.schema_version,
            attempt_number=attempt,
            latency_ms=response.latency_ms,
            recovered=bool(failures) or repaired,
            last_failure=failures[-1].category if failures else None,
        )
        return RecoveryOutcome(instruction=instruction, metadata=metadata)

    # -- Stage 1: LLM call -------------------------------------------------

    def _call_llm(
        self,
        request: LLMRequest,
        attempt: int,
        total_attempts: int,
        failures: List[FailureRecord],
    ) -> Optional[LLMResponse]:
        try:
            return self._llm_client.complete(request)
        except ConfigurationError:
            # LLM_CONFIGURATION_ERROR: never retryable, regardless of
            # attempt number -- see this module's docstring. Propagates
            # completely unmodified, exactly as Phase 3.4 did.
            raise
        except LLMTimeoutError as exc:
            self._finalize_failure(
                FailureCategory.LLM_TIMEOUT,
                "llm_call",
                str(exc),
                attempt,
                total_attempts,
                failures,
                exc,
            )
            return None
        except LLMProviderError as exc:
            self._finalize_failure(
                FailureCategory.LLM_PROVIDER_ERROR,
                "llm_call",
                str(exc),
                attempt,
                total_attempts,
                failures,
                exc,
            )
            return None

    # -- Stage 2: response parsing (with one repair attempt) --------------

    def _parse_response(
        self,
        response: LLMResponse,
        attempt: int,
        total_attempts: int,
        failures: List[FailureRecord],
    ) -> Tuple[Optional[Dict[str, Any]], bool]:
        try:
            return self._response_parser.parse(response), False
        except ResponseParsingError as exc:
            repaired_text = self._repairer.repair(response.content or "")
            if repaired_text is not None:
                repaired_response = dataclasses.replace(response, content=repaired_text)
                try:
                    return self._response_parser.parse(repaired_response), True
                except ResponseParsingError as repair_exc:
                    self._finalize_failure(
                        FailureCategory.SAFE_REPAIR_FAILED,
                        "response_parse",
                        str(repair_exc),
                        attempt,
                        total_attempts,
                        failures,
                        repair_exc,
                    )
                    return None, False

            category = self._classify_parsing_failure(response.content, exc)
            self._finalize_failure(
                category,
                "response_parse",
                str(exc),
                attempt,
                total_attempts,
                failures,
                exc,
            )
            return None, False

    @staticmethod
    def _classify_parsing_failure(
        content: Optional[str], exc: ResponseParsingError
    ) -> FailureCategory:
        if content is None or not content.strip():
            return FailureCategory.EMPTY_RESPONSE
        if "not a JSON object" in str(exc):
            return FailureCategory.UNSUPPORTED_RESPONSE
        return FailureCategory.INVALID_JSON

    # -- Stage 3: structural (schema) validation ---------------------------

    def _validate_schema(
        self,
        data: Dict[str, Any],
        attempt: int,
        total_attempts: int,
        failures: List[FailureRecord],
    ) -> Optional[ParsedInstruction]:
        try:
            return self._schema_validator.validate(data)
        except TaskValidationError as exc:
            self._finalize_failure(
                FailureCategory.SCHEMA_VALIDATION_ERROR,
                "schema_validation",
                str(exc),
                attempt,
                total_attempts,
                failures,
                exc,
            )
            return None

    # -- Stage 4: semantic validation ---------------------------------------

    def _validate_semantics(
        self,
        instruction: ParsedInstruction,
        attempt: int,
        total_attempts: int,
        failures: List[FailureRecord],
    ) -> bool:
        assert self._semantic_validator is not None
        try:
            self._semantic_validator.validate(instruction)
            return True
        except SemanticValidationError as exc:
            self._finalize_failure(
                FailureCategory.SEMANTIC_VALIDATION_ERROR,
                "semantic_validation",
                str(exc),
                attempt,
                total_attempts,
                failures,
                exc,
            )
            return False

    # -- Shared failure bookkeeping ------------------------------------------

    def _finalize_failure(
        self,
        category: FailureCategory,
        stage: str,
        message: str,
        attempt: int,
        total_attempts: int,
        failures: List[FailureRecord],
        original_exc: LanguageRuntimeError,
    ) -> None:
        """
        Records one failed attempt and either lets control return to
        the loop in `run()` (when the failure is retryable and
        attempts remain) or raises -- `original_exc` unmodified when
        this is the very first failure this `run()` call has seen
        (preserving Phase 3.4's exact exception-propagation contract,
        see this module's docstring), or `RetryExhaustedError` wrapping
        the full `failures` history once a real retry has already
        happened and the pipeline still could not succeed.
        """
        retryable = is_retryable(category)
        record = FailureRecord(
            category=category,
            stage=stage,
            message=message,
            retryable=retryable,
            attempt_number=attempt,
        )
        failures.append(record)
        logger.warning(
            "language_agent.recovery.attempt_failed",
            extra={
                "stage": stage,
                "category": category.value,
                "attempt": attempt,
                "total_attempts": total_attempts,
                "retryable": retryable,
            },
        )

        if retryable and attempt < total_attempts:
            # Another attempt will be made by the loop in `run()` --
            # nothing to raise.
            return

        if len(failures) == 1 and attempt == 1:
            # No retry has actually occurred yet -- preserve the exact
            # Phase 3.4 behavior of propagating the original,
            # stage-specific exception unmodified.
            raise original_exc

        raise RetryExhaustedError(
            f"Language runtime exhausted all recovery attempts "
            f"({len(failures)} failure(s), last category "
            f"{category.value!r}): {message}",
            failures=failures,
        ) from original_exc

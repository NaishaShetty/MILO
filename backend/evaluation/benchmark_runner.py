"""
benchmark_runner.py

Purpose
-------
Phase 3.6.1 -- Benchmark Runner. Drives `BenchmarkCase`s through
`language.agent.LanguageAgent`'s existing public interface
(`parse_with_diagnostics`) and captures the raw, unscored result of
each attempt as a `models.RawBenchmarkRecord`. This module contains no
metric/accuracy logic (that is `evaluator.py`'s and `metrics.py`'s
job) -- it is purely "run the case, record what happened", per the
spec's "the benchmark runner must NOT calculate complex metrics
itself" requirement.

How this respects "treat the Language Agent as the system under test"
-------------------------------------------------------------------------
Every collaborator wired into a `LanguageAgent` here (`PromptBuilder`,
`ResponseParser`, `SchemaValidator`, `SemanticValidator`,
`SafeResponseRepairer`, `RetryPolicy`) is the real, unmodified class
from `backend/language/`, constructed exactly the way
`backend/tests/test_language_integration.py` already does. The only
thing this module ever supplies itself is an `LLMClient` -- either the
caller's real provider client, or `StaticResponseLLMClient` below, both
of which satisfy `language.llm_client.LLMClient`'s `typing.Protocol`
structurally, exactly like every existing unit test's fake client.
Nothing here subclasses, monkeypatches, or reads a private attribute of
`LanguageAgent`.

Why `failure_cases` always use `StaticResponseLLMClient`
------------------------------------------------------------
`datasets/language/evaluation/failure_cases.json` pairs each
instruction with a `candidate_output` -- a hypothetical LLM response
engineered to exercise one specific validation/repair failure mode
(a missing comma, a bad enum, a hallucination). No real model can be
asked to reproduce a *specific* syntax error on demand, and doing so
would not be testing the model anyway -- this dataset benchmarks the
ResponseParser/SchemaValidator/repair/retry pipeline's robustness, not
a model's language understanding. `StaticResponseLLMClient` is the
mechanism that lets the *real* pipeline run against a fixed input
deterministically, without adding a single line of benchmark-specific
branching to `backend/language/*`.

Isolation
---------
`BenchmarkRunner.run()` asks `LanguageAgentFactory` for a fresh
`LanguageAgent` for every case. `LanguageAgent` itself holds no mutable
state between `parse()` calls (see `agent.py`'s docstring), so this is
a deliberate belt-and-suspenders guarantee, not a workaround for a real
statefulness problem: no case can ever be influenced by a previous
case's prompt, response, or failure history, matching the spec's
"Benchmark Isolation" requirement explicitly.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence

from evaluation.models import (
    BenchmarkCase,
    DatasetCategory,
    RawBenchmarkRecord,
    RunMode,
)
from language.agent import LanguageAgent, ParseOutcome
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
from language.llm_client import LLMClient, LLMRequest, LLMResponse
from language.prompt_builder import PromptBuilder
from language.recovery import RetryPolicy
from language.repair import SafeResponseRepairer
from language.response_parser import ResponseParser
from language.schema_validator import SchemaValidator
from language.semantic_validator import SemanticValidator

#: Production default (`language.config.RecoveryConfig.from_env()`'s
#: own default) -- used whenever a caller does not supply its own
#: `RetryPolicy`. Kept explicit here (not silently inherited from
#: `RetryPolicy`'s own `max_retries=0` default) because a benchmark run
#: with recovery disabled would never exercise Phase 3.5 at all, which
#: would silently defeat 3.6.6 (Recovery Evaluation) for any caller
#: that forgot to configure it.
DEFAULT_MAX_RETRIES = 2


class StaticResponseLLMClient:
    """
    A structural `LLMClient` (see `language.llm_client.LLMClient`'s
    `typing.Protocol`) that returns one fixed response for every call,
    regardless of the request. Used exclusively to drive
    `failure_cases` cases' `candidate_output` through the real,
    unmodified parsing/validation/repair pipeline -- see this module's
    docstring for why a real model cannot serve this role.

    Never imported by `backend/language/*` -- this class exists only in
    the evaluation framework, satisfying the runtime's own public
    Protocol from the outside, the same way every hand-written fake in
    `backend/tests/test_language_*.py` already does.
    """

    def __init__(
        self,
        content: str,
        *,
        provider: str = "static-fixture",
        model: str = "static-fixture",
    ) -> None:
        self._content = content
        self._provider = provider
        self._model = model

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Ignores `request` entirely and returns the fixed `content` -- see class docstring."""
        return LLMResponse(
            content=self._content,
            provider=self._provider,
            model=self._model,
            latency_ms=0.0,
        )


@dataclass
class LanguageAgentFactory:
    """
    Builds `LanguageAgent` instances sharing one fixed set of
    collaborators (prompt assets, parser, validators, retry policy),
    while allowing the `LLMClient` to be swapped per case. This is the
    seam that makes `BenchmarkRunner` provider-agnostic:
    `provider_comparison.py` builds one factory per provider (varying
    only `default_llm_client`), `prompt_comparison.py` builds one per
    prompt version (varying only `prompt_builder`), and both hold every
    other collaborator identical, per the spec's "keep constant:
    dataset, evaluation rules, ... recovery policy" requirement for a
    fair comparison.

    `.build()` is cheap (no I/O, no network) -- called once per case by
    `BenchmarkRunner` to guarantee isolation (see this module's
    docstring).
    """

    prompt_builder: PromptBuilder
    default_llm_client: LLMClient
    response_parser: ResponseParser
    schema_validator: SchemaValidator
    semantic_validator: Optional[SemanticValidator] = None
    repairer: Optional[SafeResponseRepairer] = None
    retry_policy: Optional[RetryPolicy] = None

    def build(self, *, llm_client: Optional[LLMClient] = None) -> LanguageAgent:
        """
        Returns a fresh `LanguageAgent`. `llm_client`, when given,
        overrides `default_llm_client` for this one agent only --
        `benchmark_runner.py` uses this to substitute a
        `StaticResponseLLMClient` for `failure_cases` cases without
        touching any other collaborator.
        """
        return LanguageAgent(
            prompt_builder=self.prompt_builder,
            llm_client=(
                llm_client if llm_client is not None else self.default_llm_client
            ),
            response_parser=self.response_parser,
            schema_validator=self.schema_validator,
            semantic_validator=self.semantic_validator,
            retry_policy=self.retry_policy
            or RetryPolicy(max_retries=DEFAULT_MAX_RETRIES),
            repairer=self.repairer,
        )

    @classmethod
    def default(
        cls, *, llm_client: LLMClient, prompt_builder: PromptBuilder
    ) -> "LanguageAgentFactory":
        """
        Convenience constructor wiring up the real Phase 3.5
        collaborators (`SemanticValidator`, `SafeResponseRepairer`) with
        the production-default retry policy -- what `run_benchmark.py`
        and most tests use unless they specifically want to test a
        stripped-down (Phase 3.4-identical) configuration.
        """
        return cls(
            prompt_builder=prompt_builder,
            default_llm_client=llm_client,
            response_parser=ResponseParser(),
            schema_validator=SchemaValidator(),
            semantic_validator=SemanticValidator(),
            repairer=SafeResponseRepairer(),
            retry_policy=RetryPolicy(max_retries=DEFAULT_MAX_RETRIES),
        )


#: Maps an *unwrapped* stage-specific exception type (raised directly by
#: `parse_with_diagnostics` when no retry ever actually occurred -- see
#: `language/recovery.py`'s `_finalize_failure`: "no retry has actually
#: occurred yet -- preserve the exact ... exception unmodified") to the
#: closed `FailureCategory` vocabulary. Best-effort for
#: `ResponseParsingError`, which covers three categories
#: (`INVALID_JSON`/`EMPTY_RESPONSE`/`UNSUPPORTED_RESPONSE`) -- refined
#: by message inspection in `_classify_response_parsing_error`, mirroring
#: `RecoveryEngine._classify_parsing_failure`'s own heuristic exactly so
#: the two never disagree.
_EXCEPTION_CATEGORY = {
    LLMTimeoutError: FailureCategory.LLM_TIMEOUT,
    LLMProviderError: FailureCategory.LLM_PROVIDER_ERROR,
    TaskValidationError: FailureCategory.SCHEMA_VALIDATION_ERROR,
    SemanticValidationError: FailureCategory.SEMANTIC_VALIDATION_ERROR,
    ConfigurationError: FailureCategory.LLM_CONFIGURATION_ERROR,
    PromptLoadError: FailureCategory.LLM_CONFIGURATION_ERROR,
}


def _classify_response_parsing_error(exc: ResponseParsingError) -> FailureCategory:
    message = str(exc)
    if "empty" in message.lower():
        return FailureCategory.EMPTY_RESPONSE
    if "not a JSON object" in message:
        return FailureCategory.UNSUPPORTED_RESPONSE
    return FailureCategory.INVALID_JSON


def _classify_exception(exc: LanguageRuntimeError) -> FailureCategory:
    """Best-effort category for an unwrapped, single-attempt exception -- see `_EXCEPTION_CATEGORY`."""
    if isinstance(exc, ResponseParsingError):
        return _classify_response_parsing_error(exc)
    for exc_type, category in _EXCEPTION_CATEGORY.items():
        if isinstance(exc, exc_type):
            return category
    # Closed taxonomy has no better answer -- `RETRY_EXHAUSTED` is the
    # only category left that always means "something failed and no
    # more specific classification is available", never fabricated as
    # a new category (per the spec's "do not invent new categories").
    return FailureCategory.RETRY_EXHAUSTED


def _serialize_candidate_output(candidate_output: object) -> str:
    """
    `failure_cases.json`'s `candidate_output` is a raw string for
    syntactically-invalid-JSON cases, or a dict for schema/semantic
    violation cases -- `StaticResponseLLMClient` needs a single string
    either way (mirroring what a real provider's `LLMResponse.content`
    always is).
    """
    if isinstance(candidate_output, str):
        return candidate_output
    return json.dumps(candidate_output)


class BenchmarkRunner:
    """
    Phase 3.6.1's orchestrator: given a `LanguageAgentFactory` and a
    sequence of `BenchmarkCase`s, produces one `RawBenchmarkRecord` per
    case. Contains no evaluation/scoring logic -- see this module's
    docstring.
    """

    def __init__(
        self,
        agent_factory: LanguageAgentFactory,
        *,
        case_limit: Optional[int] = None,
        run_mode: RunMode = RunMode.MOCKED,
    ) -> None:
        self._agent_factory = agent_factory
        # `case_limit` is the spec's "Cost and Safety" control --
        # "Require: ... Configurable case limits" -- so a real-provider
        # run can be capped without editing dataset files.
        self._case_limit = case_limit
        # Recorded verbatim on every produced record and on
        # `RunMetadata` (see `result_store.py`) -- the caller (typically
        # `run_benchmark.py`) is the one place that actually knows
        # whether `agent_factory.default_llm_client` is a real provider
        # client or a test fixture, so that decision is passed in rather
        # than guessed here from the client's type.
        self._run_mode = run_mode

    def run(self, cases: Sequence[BenchmarkCase]) -> List[RawBenchmarkRecord]:
        """Runs every case in `cases` (respecting `case_limit`), in order, sequentially."""
        selected = (
            list(cases)[: self._case_limit]
            if self._case_limit is not None
            else list(cases)
        )
        return [self._run_case(case) for case in selected]

    def _run_case(self, case: BenchmarkCase) -> RawBenchmarkRecord:
        run_mode = self._run_mode
        llm_client_override = None
        if case.dataset == DatasetCategory.FAILURE:
            # See this module's docstring: `failure_cases` are always
            # driven through a deterministic fixture, independent of
            # whichever `LLMClient` the factory's `default_llm_client`
            # is (real or mocked) -- that's what makes this dataset's
            # results comparable across providers in the first place
            # (the "LLM" is held constant; only the validation pipeline
            # is exercised).
            llm_client_override = StaticResponseLLMClient(
                _serialize_candidate_output(case.candidate_output)
            )
            run_mode = RunMode.MOCKED

        agent = self._agent_factory.build(llm_client=llm_client_override)

        started = time.perf_counter()
        try:
            outcome: ParseOutcome = agent.parse_with_diagnostics(case.instruction)
        except RetryExhaustedError as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return RawBenchmarkRecord(
                case_id=case.case_id,
                dataset=case.dataset,
                category=case.category,
                succeeded=False,
                error_type=type(exc).__name__,
                error_message=str(exc),
                failure_records=[
                    {
                        "category": record.category.value,
                        "stage": record.stage,
                        "message": record.message,
                        "retryable": record.retryable,
                        "attempt_number": record.attempt_number,
                    }
                    for record in exc.failures
                ],
                total_latency_ms=elapsed_ms,
                run_mode=run_mode,
            )
        except LanguageRuntimeError as exc:
            # Unwrapped, single-attempt failure -- see `_classify_exception`.
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            category = _classify_exception(exc)
            return RawBenchmarkRecord(
                case_id=case.case_id,
                dataset=case.dataset,
                category=case.category,
                succeeded=False,
                error_type=type(exc).__name__,
                error_message=str(exc),
                failure_records=[
                    {
                        "category": category.value,
                        "stage": "unknown",
                        "message": str(exc),
                        "retryable": False,
                        "attempt_number": 1,
                    }
                ],
                total_latency_ms=elapsed_ms,
                run_mode=run_mode,
            )

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        metadata = outcome.metadata
        return RawBenchmarkRecord(
            case_id=case.case_id,
            dataset=case.dataset,
            category=case.category,
            succeeded=True,
            parsed_instruction=outcome.instruction.model_dump(mode="json"),
            provider=metadata.provider,
            model=metadata.model,
            prompt_version=metadata.prompt_version,
            schema_version=metadata.schema_version,
            attempt_number=metadata.attempt_number,
            llm_latency_ms=metadata.latency_ms,
            recovered=metadata.recovered,
            last_failure_category=(
                metadata.last_failure.value if metadata.last_failure else None
            ),
            total_latency_ms=elapsed_ms,
            run_mode=run_mode,
        )

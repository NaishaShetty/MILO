"""
agent.py

Purpose
-------
Defines `LanguageAgent`, the top-level orchestrator for the Language
Parsing Runtime -- the single entry point that turns a raw natural
language instruction into a validated `ParsedInstruction`
(`backend/schemas/task.py`) for a future Planner (Phase 4) to consume.
This is the class every future caller (a CLI, Phase 3.7's API layer,
or a test) is expected to depend on; nothing else in
`backend/language/` is meant to be used directly by code outside this
package.

Why this class is intentionally "thin"
-------------------------------------------
`LanguageAgent` coordinates five collaborators -- `PromptBuilder`,
`RecoveryEngine` (which itself wraps `LLMClient`, `ResponseParser`,
`SchemaValidator`, and an optional `SemanticValidator` -- see
`recovery.py`), and contains no logic that belongs to any of them. It
does not know how `parser_prompt.txt` is formatted, which HTTP
endpoint an LLM provider exposes, how markdown code fences get
stripped from a response, how Pydantic resolves a discriminated union,
or which `FailureCategory` is worth retrying. Every one of those
concerns has exactly one owning file elsewhere in this package (see
each file's own docstring). Phase 3.5 added an entire new
responsibility to this runtime -- output validation, failure
classification, retry, repair, and semantic checking -- and every bit
of it lives in `failures.py`, `repair.py`, `semantic_validator.py`, and
`recovery.py`, never inlined here. An orchestrator that starts
absorbing "just one small piece" of a collaborator's logic is how
orchestrators become unmaintainable god-objects; this file remaining
almost unchanged in *shape* between Phase 3.4 and Phase 3.5, while the
runtime's actual robustness grew substantially, is the intended proof
that boundary held.

Dependency injection, and why `from_config` exists alongside it
----------------------------------------------------------------------
`LanguageAgent.__init__` takes already-constructed collaborator
instances -- never a config object it would build them from itself.
This is what makes the class trivially testable: a test constructs a
`LanguageAgent` with a hand-written fake `LLMClient` (satisfying the
`LLMClient` protocol structurally, per `llm_client.py`) and real
instances of the other collaborators, and can assert on end-to-end
orchestration with zero network access and zero mocking frameworks
patching internals. `LanguageAgent.from_config()` is a convenience
*factory*, not an alternate code path: it exists only so production
call sites don't need to repeat this wiring by hand, and it delegates
to the exact same `__init__`.

Backward compatibility with Phase 3.4
-------------------------------------------
Every new Phase 3.5 collaborator (`semantic_validator`, `retry_policy`,
`repairer`) is an *optional*, keyword-only constructor argument
defaulting to "off": no semantic validation, and a `RetryPolicy` with
`max_retries=0` (see `recovery.py`). A `LanguageAgent` built the exact
way Phase 3.4's test suite already builds it --
`LanguageAgent(prompt_builder, llm_client, response_parser,
schema_validator)` -- therefore behaves *identically* to Phase 3.4:
one attempt, and any collaborator's exception propagates completely
unmodified. `from_config()` is the only place these new collaborators
are enabled by default for production use.

The `parse()` contract
---------------------------
`parse(instruction: str) -> ParsedInstruction` is unchanged from Phase
3.4: it either returns a validated `SingleTask`/`MultiTask`, or raises
a `LanguageRuntimeError` subclass (see `exceptions.py`) -- it never
returns `None`, a raw dict, or a partially-validated object, and it
never silently swallows a failure. A task with `needs_clarification=True`
is a *successful* parse (a valid `SingleTask` the schema explicitly
allows to represent "the robot needs more information") -- routing
that to a clarification flow is the caller's responsibility, not an
error this class raises. See `backend/docs/language_interface_spec.md`
section 13 ("Ambiguity Handling") for why that is correct behavior.

`parse_with_diagnostics()`, added in Phase 3.5, is additive: same
success/failure contract as `parse()`, but returns a `ParseOutcome`
carrying `RuntimeMetadata` (provider, model, attempt count, whether
recovery salvaged the result, ...) alongside the instruction, for a
future Phase 3.6 benchmark harness or Phase 3.7 API layer that needs
that data. `parse()` itself is implemented in terms of this method, not
duplicated, so the two can never drift.

What this phase explicitly does not do
-------------------------------------------
No Planner call, no `Scene` access, no robot action -- `ParsedInstruction`
is this class's entire output; what happens to it next is out of scope
here by design. No user-facing conversation loop for clarification
(see `recovery.py`'s module docstring and this project's Phase 3.5
scope note "Do not implement the user conversation loop yet").
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from language.config import LanguageRuntimeConfig
from language.exceptions import LanguageRuntimeError
from language.failures import RuntimeMetadata
from language.llm_client import LLMClient
from language.prompt_builder import PromptBuilder
from language.provider_factory import create_llm_client
from language.recovery import RecoveryEngine, RecoveryOutcome, RetryPolicy
from language.repair import SafeResponseRepairer
from language.response_parser import ResponseParser
from language.schema_validator import SchemaValidator
from language.semantic_validator import SemanticValidator
from schemas.task import ParsedInstruction

# Module-level logger, not a project-wide logging framework: this
# repository's Observability requirements explicitly ask to avoid
# introducing logging infrastructure this project doesn't already
# have. Structured context is attached via `extra=` so a future log
# aggregator can filter/query by field without this module needing to
# know anything about how logs are eventually shipped or stored.
logger = logging.getLogger(__name__)


class ParseOutcome:
    """
    The Phase 3.5 result type of `parse_with_diagnostics()`: a
    validated `ParsedInstruction` plus the `RuntimeMetadata`
    (`failures.py`) describing how it was obtained.

    Kept as a plain class (not a `NamedTuple`/`dataclass`) only because
    it needs no more than attribute access and a readable `repr` --
    matching this project's "no unnecessary abstractions" requirement.
    Not used as `parse()`'s return type, deliberately: changing
    `parse()`'s return type would break every Phase 3.4 caller that
    already depends on receiving a `ParsedInstruction` directly (see
    this module's docstring, "Backward compatibility with Phase 3.4").
    """

    __slots__ = ("instruction", "metadata")

    def __init__(
        self, instruction: ParsedInstruction, metadata: RuntimeMetadata
    ) -> None:
        self.instruction = instruction
        self.metadata = metadata

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"ParseOutcome(instruction={self.instruction!r}, metadata={self.metadata!r})"


class LanguageAgent:
    """
    Orchestrates one natural-language-instruction-to-`ParsedInstruction`
    pipeline. See this module's docstring for the full rationale behind
    every design decision below; this class itself intentionally
    contains almost no comments beyond structural ones, since its whole
    point is to be simple enough not to need them.
    """

    def __init__(
        self,
        prompt_builder: PromptBuilder,
        llm_client: LLMClient,
        response_parser: ResponseParser,
        schema_validator: SchemaValidator,
        *,
        semantic_validator: Optional[SemanticValidator] = None,
        retry_policy: Optional[RetryPolicy] = None,
        repairer: Optional[SafeResponseRepairer] = None,
    ) -> None:
        self._prompt_builder = prompt_builder
        self._recovery_engine = RecoveryEngine(
            llm_client=llm_client,
            response_parser=response_parser,
            schema_validator=schema_validator,
            semantic_validator=semantic_validator,
            repairer=repairer,
            retry_policy=retry_policy,
        )

    @classmethod
    def from_config(
        cls, config: Optional[LanguageRuntimeConfig] = None
    ) -> "LanguageAgent":
        """
        Convenience factory for production use: wires up a real
        `PromptBuilder` and the `LLMClient` implementation matching
        `config.llm.provider` (via `provider_factory.create_llm_client`
        -- OpenAI or Gemini today, see that module), from `config` (or
        from the environment, via `LanguageRuntimeConfig.from_env()`,
        if `config` is omitted). Unlike the bare `LanguageAgent(...)`
        constructor, this factory enables Phase 3.5's recovery
        behavior by default: semantic validation is turned on, and the
        retry policy is read from `RecoveryConfig`
        (`LANGUAGE_RUNTIME_MAX_RETRIES`, default 2) -- production use
        is exactly where this project wants robustness against
        real-world LLM failures active by default.

        Tests should prefer calling `LanguageAgent(...)` directly with
        injected fakes rather than this method -- see this module's
        docstring on dependency injection for why.
        """
        resolved_config = config or LanguageRuntimeConfig.from_env()
        return cls(
            prompt_builder=PromptBuilder(resolved_config.prompts),
            llm_client=create_llm_client(resolved_config.llm),
            response_parser=ResponseParser(),
            schema_validator=SchemaValidator(),
            semantic_validator=SemanticValidator(),
            retry_policy=RetryPolicy(max_retries=resolved_config.recovery.max_retries),
        )

    def parse(self, instruction: str) -> ParsedInstruction:
        """
        Runs one instruction through the full pipeline and returns the
        resulting `ParsedInstruction`. See this module's docstring for
        the full success/failure contract, and `recovery.py` for
        exactly when a collaborator failure is retried versus
        propagated. Implemented in terms of `parse_with_diagnostics()`
        so the two can never disagree about behavior.
        """
        return self.parse_with_diagnostics(instruction).instruction

    def parse_with_diagnostics(self, instruction: str) -> ParseOutcome:
        """
        Same pipeline as `parse()`, but returns a `ParseOutcome`
        carrying `RuntimeMetadata` alongside the result -- see this
        module's docstring for why this is a separate, additive method
        rather than a change to `parse()`'s return type.
        """
        started_at = time.monotonic()
        # Logged as instruction *length*, never the instruction text
        # itself or any LLM response content -- see this repository's
        # Observability requirements ("do not log full user prompts or
        # raw model responses").
        logger.info(
            "language_agent.parse.start",
            extra={"instruction_length": len(instruction)},
        )

        try:
            request = self._prompt_builder.build(instruction)
        except LanguageRuntimeError:
            logger.warning(
                "language_agent.parse.failed", extra={"stage": "prompt_build"}
            )
            raise

        try:
            outcome: RecoveryOutcome = self._recovery_engine.run(request)
        except LanguageRuntimeError:
            # `RecoveryEngine` has already logged each individual
            # attempt's failure (see `recovery.py`'s
            # `_finalize_failure`) -- this log line marks that the
            # overall `parse()` call, not just one attempt, ended in
            # failure.
            logger.warning(
                "language_agent.parse.failed",
                extra={
                    "stage": "recovery",
                    "prompt_version": request.prompt_version,
                    "schema_version": request.schema_version,
                },
            )
            raise

        elapsed_ms = (time.monotonic() - started_at) * 1000.0
        logger.info(
            "language_agent.parse.success",
            extra={
                "prompt_version": outcome.metadata.prompt_version,
                "schema_version": outcome.metadata.schema_version,
                "provider": outcome.metadata.provider,
                "model": outcome.metadata.model,
                "attempt_number": outcome.metadata.attempt_number,
                "recovered": outcome.metadata.recovered,
                "llm_latency_ms": outcome.metadata.latency_ms,
                "total_latency_ms": elapsed_ms,
                "task_type": outcome.instruction.task_type,
                "needs_clarification": outcome.instruction.needs_clarification,
            },
        )
        return ParseOutcome(instruction=outcome.instruction, metadata=outcome.metadata)

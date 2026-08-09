"""
schema_validator.py

Purpose
-------
The final gate in the Language Parsing Runtime pipeline: takes the
plain Python `dict` produced by `ResponseParser` and validates it
against Phase 3.2's `ParsedInstruction` schema
(`backend/schemas/task.py`), returning a real `SingleTask` or
`MultiTask` instance -- never a raw dict -- to `LanguageAgent`.

Why this file contains (almost) no logic of its own
--------------------------------------------------------
Phase 3.2 already built the single source of truth for what a valid
task looks like: closed enum vocabularies (`schemas/enums.py`),
cross-field invariants (`needs_clarification` consistency, subtask
count bounds, goal snake_case formatting -- `schemas/validators.py`),
and the discriminated union (`ParsedInstruction`) that resolves raw
`task_type` values to the right concrete model. Re-implementing any of
that here -- even partially, even as a "quick sanity check" before
deferring to Pydantic -- would create a second, driftable copy of
validation rules that Phase 3.2's own 70-case test suite
(`backend/tests/test_task.py`) does not protect. This module's entire
job is to be a thin, honest adapter: call Phase 3.2's validator, and
translate its one possible failure (`pydantic.ValidationError`) into
this package's own exception vocabulary
(`exceptions.TaskValidationError`) so `LanguageAgent`'s caller never
needs to import `pydantic` directly to handle a validation failure.

Which component depends on this file
---------------------------------------
`LanguageAgent` (`agent.py`) calls `SchemaValidator.validate()` as the
last step of `parse()`. Nothing downstream of `LanguageAgent` (a future
Planner, Phase 3.7's API layer) is expected to call this class
directly -- they receive an already-validated `ParsedInstruction` and
never see the intermediate dict this class consumes.
"""

from __future__ import annotations

from typing import Any, Dict

from pydantic import TypeAdapter, ValidationError

from language.exceptions import TaskValidationError
from schemas.task import ParsedInstruction


class SchemaValidator:
    """
    Thin wrapper around a cached `pydantic.TypeAdapter(ParsedInstruction)`.

    The adapter is built once per `SchemaValidator` instance, not once
    per `validate()` call: `TypeAdapter` construction does non-trivial
    work (resolving the discriminated union, building the union's
    validators) that has no reason to repeat on every call in a
    request/response service loop -- see this repository's Performance
    requirements for Phase 3.4 ("cache static assets so they are not
    reloaded/rebuilt when unnecessary"). A single `LanguageAgent`
    instance is expected to own one long-lived `SchemaValidator`.
    """

    def __init__(self) -> None:
        # `ParsedInstruction` is the Phase 3.2 discriminated union
        # (`Union[SingleTask, MultiTask]` keyed on `task_type`) -- see
        # `schemas/task.py`'s own comment on why that discriminator
        # lets Pydantic pick the right concrete model directly from raw
        # input, with no branching logic needed on this class's part.
        self._adapter: TypeAdapter[ParsedInstruction] = TypeAdapter(ParsedInstruction)

    def validate(self, data: Dict[str, Any]) -> ParsedInstruction:
        """
        Validates `data` (as produced by `ResponseParser.parse()`)
        against `ParsedInstruction` and returns the resulting
        `SingleTask` or `MultiTask`. Raises `TaskValidationError`,
        preserving the original `pydantic.ValidationError` as
        `original_error`, on any validation failure -- a missing
        required field, an unrecognized enum value, or a violated
        cross-field invariant (all enforced by Phase 3.2's own
        validators, not re-checked here).
        """
        try:
            return self._adapter.validate_python(data)
        except ValidationError as exc:
            # `str(exc)` already produces Pydantic's own human-readable,
            # per-field error summary -- reused as this exception's
            # message rather than reformatted, so the two never drift
            # out of sync. `original_error` keeps `.errors()` (the
            # structured, machine-readable form) available to any
            # caller that wants it -- see `TaskValidationError`'s own
            # docstring for why that matters.
            raise TaskValidationError(str(exc), original_error=exc) from exc

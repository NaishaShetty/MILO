"""
failures.py (backend/agents)

Purpose
-------
The closed, cross-agent failure taxonomy the phase brief's section
7.12 asks for (`VISION_FAILURE`, `OBJECT_NOT_FOUND`,
`OBJECT_NOT_VISIBLE`, `NAVIGATION_FAILURE`, `PATH_BLOCKED`,
`ACTION_FAILURE`, `INVALID_ACTION`, `INVALID_PLAN`,
`ENVIRONMENT_CHANGED`, `MEMORY_FAILURE`, `TIMEOUT`, `UNKNOWN_FAILURE`).

Why this does not replace `execution.errors.ExecutionErrorCode`
----------------------------------------------------------------------
`execution/errors.py` already has a closed, well-tested taxonomy --
but it is scoped to *execution* failures only (a dispatched action
failed). Vision (no detection), memory (retrieval/store failure), and
planning (an invalid plan) can each fail too, and `ReflectionAgent`
needs one vocabulary that spans all of them, not four separate enums
to pattern-match against. `from_execution_error()` below is the one
translation point: every `ExecutionErrorCode` maps to exactly one
`FailureCategory`, so `execution/` keeps its own enum exactly as-is
(no rename, no new dependency added to that package) while
`ReflectionAgent`/`NavigationAgent` reason in the wider vocabulary.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field

from execution.errors import ExecutionErrorCode


class FailureCategory(str, Enum):
    """Every category of failure any Phase 7 agent can report."""

    VISION_FAILURE = "VISION_FAILURE"
    OBJECT_NOT_FOUND = "OBJECT_NOT_FOUND"
    OBJECT_NOT_VISIBLE = "OBJECT_NOT_VISIBLE"
    NAVIGATION_FAILURE = "NAVIGATION_FAILURE"
    PATH_BLOCKED = "PATH_BLOCKED"
    ACTION_FAILURE = "ACTION_FAILURE"
    INVALID_ACTION = "INVALID_ACTION"
    INVALID_PLAN = "INVALID_PLAN"
    ENVIRONMENT_CHANGED = "ENVIRONMENT_CHANGED"
    MEMORY_FAILURE = "MEMORY_FAILURE"
    TIMEOUT = "TIMEOUT"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class AgentFailure(BaseModel):
    """
    One structured, cross-agent failure -- the record `ReflectionAgent`
    reasons over and (per section 7.12) carries "useful context for
    debugging, reflection, replanning, logging, experiments".
    """

    model_config = ConfigDict(extra="forbid")

    category: FailureCategory
    message: str
    agent: str = Field(description="Name of the agent that reported this failure.")
    recoverable: bool = Field(
        default=False,
        description="Mirrors execution.errors.ExecutionError.recoverable's "
        "informational-only judgment -- ReflectionAgent's input, never "
        "acted on by the reporting agent itself.",
    )
    details: Dict[str, Any] = Field(default_factory=dict)


#: `ExecutionErrorCode` -> `FailureCategory`, one entry per code (see
#: `test_agents_failures.py` for the exhaustiveness check).
_EXECUTION_ERROR_MAP: Dict[ExecutionErrorCode, FailureCategory] = {
    ExecutionErrorCode.INVALID_ACTION: FailureCategory.INVALID_ACTION,
    ExecutionErrorCode.INVALID_PARAMETER: FailureCategory.INVALID_PLAN,
    ExecutionErrorCode.PRECONDITION_FAILED: FailureCategory.ACTION_FAILURE,
    ExecutionErrorCode.OBJECT_NOT_FOUND: FailureCategory.OBJECT_NOT_FOUND,
    ExecutionErrorCode.TARGET_NOT_FOUND: FailureCategory.OBJECT_NOT_FOUND,
    ExecutionErrorCode.OBJECT_NOT_REACHABLE: FailureCategory.NAVIGATION_FAILURE,
    ExecutionErrorCode.NAVIGATION_FAILED: FailureCategory.NAVIGATION_FAILURE,
    ExecutionErrorCode.SIMULATOR_ERROR: FailureCategory.ACTION_FAILURE,
    ExecutionErrorCode.ACTION_TIMEOUT: FailureCategory.TIMEOUT,
    ExecutionErrorCode.EXECUTION_CANCELLED: FailureCategory.ACTION_FAILURE,
    ExecutionErrorCode.VALIDATION_FAILED: FailureCategory.INVALID_PLAN,
    ExecutionErrorCode.UNKNOWN_ERROR: FailureCategory.UNKNOWN_FAILURE,
}


def from_execution_error(
    code: ExecutionErrorCode, *, message: str, agent: str = "execution", **kwargs: Any
) -> AgentFailure:
    """
    Translates an `execution.errors.ExecutionErrorCode` into the shared
    `AgentFailure`/`FailureCategory` vocabulary. `kwargs` (`recoverable`,
    `details`) pass straight through to `AgentFailure` -- callers
    already holding an `ExecutionError` are expected to pass its own
    `recoverable`/`details` fields, never re-derive them.
    """
    category = _EXECUTION_ERROR_MAP.get(code, FailureCategory.UNKNOWN_FAILURE)
    return AgentFailure(category=category, message=message, agent=agent, **kwargs)


def category_for_execution_error(code: ExecutionErrorCode) -> FailureCategory:
    """The bare mapping, for callers (e.g. `NavigationAgent`) that want
    to refine a category further before building an `AgentFailure`."""
    return _EXECUTION_ERROR_MAP.get(code, FailureCategory.UNKNOWN_FAILURE)

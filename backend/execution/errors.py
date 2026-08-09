"""
errors.py (backend/execution)

Purpose
-------
The closed, machine-readable error taxonomy for everything that can go
wrong while executing a `Plan` -- section 23's requirement. Every
failure this package reports (a precondition that did not hold, a
simulator call that failed, a timeout, a cancellation, ...) is reported
as one of these codes, never an arbitrary string, so a caller (the API,
the frontend, a future replanning/Memory module) can branch on
`ExecutionError.code` instead of pattern-matching `message` text --
exactly the same rationale `planner.models.ValidationIssue.code`
already documents for Phase 4.

Why a flat enum, not a `PlanningError`-style exception hierarchy
--------------------------------------------------------------------
`planner.exceptions.PlanningError` is a *raised* exception hierarchy
because a planner either returns a `PlanningResult` or throws for a
genuine programmer/configuration error. Execution failures are
different: a failed step is normal, expected, *returned* output (the
whole point of `ActionResult`/`ExecutionRecord`), never a raised
exception -- see `exceptions.py`'s docstring for the (much narrower)
set of things this package does raise. A flat, serializable enum is
the right shape for "normal, returned, structured failure data";
`exceptions.py` is the right shape for "this package cannot proceed at
all."
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class ExecutionErrorCode(str, Enum):
    """
    Every category of execution failure this package can report.
    Deliberately small and closed -- see this module's docstring.
    """

    INVALID_ACTION = "INVALID_ACTION"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    OBJECT_NOT_FOUND = "OBJECT_NOT_FOUND"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    OBJECT_NOT_REACHABLE = "OBJECT_NOT_REACHABLE"
    NAVIGATION_FAILED = "NAVIGATION_FAILED"
    SIMULATOR_ERROR = "SIMULATOR_ERROR"
    ACTION_TIMEOUT = "ACTION_TIMEOUT"
    EXECUTION_CANCELLED = "EXECUTION_CANCELLED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class ExecutionError(BaseModel):
    """
    One structured, reportable execution failure -- section 9's
    "Failure Handling" contract. Attached to an `ActionResult` (one
    action's failure) and, when it is the failure that stops a `Plan`,
    to the top-level `ExecutionRecord.error` as well.

    `recoverable` is this package's own judgment about whether a
    *future* replanning/retry layer could plausibly succeed by trying
    again or trying a different approach (e.g. `OBJECT_NOT_REACHABLE`
    is recoverable -- a different approach angle might work;
    `INVALID_ACTION` is not -- the plan itself is malformed). This
    package never acts on that judgment itself (see this project's "do
    not implement unrestricted dynamic replanning yet" rule); it is
    exposed purely as data for a future consumer to act on.
    """

    model_config = ConfigDict(extra="forbid")

    code: ExecutionErrorCode
    message: str = Field(description="Human-readable explanation of the failure.")
    step_id: Optional[int] = Field(
        default=None, description="1-indexed PlanStep this error concerns, if any."
    )
    action: Optional[str] = Field(
        default=None, description="Abstract action name this error concerns, if any."
    )
    recoverable: bool = Field(
        default=False,
        description="Whether a future retry/replanning layer could plausibly "
        "resolve this without redesigning the plan. Informational only -- "
        "this package never retries or replans based on this field itself "
        "beyond the bounded, explicit retry `ExecutionController` already "
        "supports (see that module's docstring).",
    )
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured extra context (e.g. the AI2-THOR "
        "errorMessage, the objectId that could not be resolved). Open "
        "on purpose -- see planner.models's rationale for `metadata` "
        "being an open dict where the calling context can vary.",
    )

"""
models.py (backend/execution)

Purpose
-------
The typed, serializable data model for everything this package produces
or consumes: `ActionType` + `Action` (section 2's "standardized action
model"), `ActionResult` (section 7), `ExecutionEvent` (section 11), and
`ExecutionStatus` + `ExecutionRecord` (sections 5 and 12). Like
`planner/models.py`, this module holds ONLY data -- no dispatch logic
(`dispatcher.py`), no precondition logic (`preconditions.py`), no
result-validation logic (`validator.py`), no sequencing logic
(`controller.py`).

Why `Action` is a separate type from `planner.models.PlanStep`
--------------------------------------------------------------------
A `PlanStep` is a Phase 4 concept: one line in an abstract,
simulator-independent plan (`action="navigate"`, `target="apple"`). An
`Action` is a Phase 5 concept: one concrete, dispatchable unit this
package's `ActionDispatcher` can translate into exactly one `Simulator`
call (`action_type=ActionType.NAVIGATE`,
`parameters={"object_id": "Apple|+00.90|..."}`). `controller.py` builds
an `Action` from a `PlanStep` (via `resolver.py` for the `objectId`
translation) for exactly this reason: keeping the two types distinct is
what keeps Phase 4's plan schema untouched by Phase 5's simulator-facing
concerns (`object_id`, not `target`) -- see `__init__.py`'s module
docstring on why this package never rewrites Phase 4's action
vocabulary.

Design notes
------------
- Pydantic (matching `planner/models.py`'s convention) for free JSON
  (de)serialization across the API boundary. `extra="forbid"`
  everywhere -- same "fail loudly, not silently" rationale.
- `ActionResult`/`ExecutionEvent` are intentionally flat and
  JSON-simple (no nested simulator objects) so they can be logged,
  returned over HTTP, and -- per section 26 -- consumed by a future
  Phase 6 Memory Agent without that module needing to know anything
  about this package's internals.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from execution.errors import ExecutionError, ExecutionErrorCode
from planner.models import StepStatus


class ActionType(str, Enum):
    """
    Every concrete, dispatchable action `ActionDispatcher` knows how to
    translate into a `Simulator` call. Deliberately a small, closed set
    matching `simulator.simulator.Simulator`'s own method surface --
    adding a new `ActionType` and adding a new `Simulator` method are
    the same change, by design (see `dispatcher.py`).
    """

    MOVE_AHEAD = "move_ahead"
    MOVE_BACK = "move_back"
    ROTATE_LEFT = "rotate_left"
    ROTATE_RIGHT = "rotate_right"
    LOOK_UP = "look_up"
    LOOK_DOWN = "look_down"
    NAVIGATE = "navigate"
    PICKUP = "pickup"
    PUT = "put"
    OPEN = "open"
    CLOSE = "close"
    # `locate` has no simulator-side effect (Phase 4's symbolic
    # "perceive this object" step) -- `ActionDispatcher` handles it as
    # a documented no-op rather than refusing to dispatch it, so a
    # Phase-4-generated plan never fails execution purely because it
    # contains a `locate` step. See `dispatcher.py`.
    LOCATE = "locate"


class Action(BaseModel):
    """
    One concrete, dispatchable action -- section 2's action model.
    `parameters` is a typed-enough open dict (matching
    `planner.models.PlanStep.parameters`'s own precedent): every action
    this package actually dispatches reads a well-known key
    (`object_id`, and for `put`, `container_id`) documented per
    `ActionType` in `dispatcher.py`, but the type stays a dict rather
    than one Pydantic model per `ActionType` so a new action type is a
    `dispatcher.py` change, not a schema migration.
    """

    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action_type: ActionType
    parameters: Dict[str, Any] = Field(default_factory=dict)
    step_id: Optional[int] = Field(
        default=None,
        description="The PlanStep.step_id this Action was built from, if any "
        "-- None for an Action dispatched outside of plan execution "
        "(e.g. a future manual/teleop action).",
    )


class ActionResult(BaseModel):
    """
    The standardized outcome of dispatching one `Action` -- section 7 /
    section 8. Always produced by `validator.ResultValidator`, never
    hand-constructed by `controller.py` or `dispatcher.py` directly, so
    "was this actually validated" is never in question.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    action: str = Field(description="ActionType.value this result is for.")
    action_id: str
    step_id: Optional[int] = None
    object_id: Optional[str] = None
    target_id: Optional[str] = None
    error: Optional[str] = Field(
        default=None, description="Human-readable error message, or None on success."
    )
    error_code: Optional[ExecutionErrorCode] = None
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Simulator-observed state relevant to this result (e.g. "
        "{'isOpen': True} for an `open` action, or "
        "{'lastActionSuccess': False, 'errorMessage': ...} for a raw "
        "simulator failure) -- never fabricated, always read from the "
        "actual AI2-THOR event/metadata this action produced.",
    )
    duration_ms: float = 0.0
    retry_count: int = 0
    timestamp: float = Field(default_factory=time.time)


class ExecutionStatus(str, Enum):
    """
    Lifecycle of one `ExecutionRecord` (one call to
    `ExecutionController.execute_plan()`) -- section 5's plan-level
    states, kept as this package's own enum rather than reusing
    `planner.models.PlanStatus` directly: an `ExecutionRecord` is a
    Phase-5-owned run of a plan (a caller may execute the same `Plan`
    more than once, each with its own `execution_id`), so it needs its
    own identity and lifecycle distinct from the `Plan` object itself
    -- which `ExecutionController` still also updates in place (see
    `controller.py`) so a client reading `Plan.status` directly sees
    the same picture.
    """

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionEvent(BaseModel):
    """
    One structured, loggable execution event -- section 11. Emitted by
    `ExecutionController` for every step start/finish (success or
    failure) and appended to `ExecutionRecord.events`, and also passed
    to this project's standard `logging` module (see `controller.py`)
    so operators get the same information in server logs without a
    second, divergent logging mechanism -- section 11's "should be
    compatible with future Memory Agent... not tightly coupled to a
    specific database" requirement is satisfied by keeping this a plain
    serializable record, not by inventing a bespoke event bus.
    """

    model_config = ConfigDict(extra="forbid")

    timestamp: float = Field(default_factory=time.time)
    execution_id: str
    plan_id: str
    step_id: Optional[int] = None
    action: str
    target: Optional[str] = None
    status: str = Field(
        description="'started' | 'success' | 'failed' | 'skipped' | 'blocked' "
        "| 'cancelled' -- the step-level outcome this event reports."
    )
    duration_ms: Optional[float] = None
    error_code: Optional[ExecutionErrorCode] = None
    message: Optional[str] = None


class StepExecutionRecord(BaseModel):
    """
    Everything `ExecutionController` learned about one `PlanStep`
    during one execution run -- the step-level detail
    `ExecutionRecord.step_results` carries alongside the `Plan` object
    itself (which only carries `PlanStep.status`, not full result
    detail).
    """

    model_config = ConfigDict(extra="forbid")

    step_id: int
    action: str
    target: Optional[str] = None
    status: StepStatus
    result: Optional[ActionResult] = None
    error: Optional[ExecutionError] = None


class ExecutionRecord(BaseModel):
    """
    The full record of one `ExecutionController.execute_plan()` run --
    section 12's "Execution History" and section 26's "clean execution
    records that Phase 6 can consume." Deliberately storage-agnostic:
    this package never writes it to a database or file itself (see
    `controller.py`'s docstring) -- `api/routes/execution.py` keeps
    these in an in-memory store for the lifetime of the process and
    returns them as plain JSON, which is exactly the shape a future
    Phase 6 Memory Agent is expected to persist as an episodic
    experience (section 26's example JSON maps directly onto this
    model's fields).
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    execution_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    plan_id: str
    task_id: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    step_results: List[StepExecutionRecord] = Field(default_factory=list)
    events: List[ExecutionEvent] = Field(default_factory=list)
    error: Optional[ExecutionError] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    @property
    def duration_ms(self) -> Optional[float]:
        if self.started_at is None or self.finished_at is None:
            return None
        return (self.finished_at - self.started_at) * 1000.0

    @property
    def success_count(self) -> int:
        return sum(1 for s in self.step_results if s.status == StepStatus.COMPLETED)

    @property
    def failure_count(self) -> int:
        return sum(1 for s in self.step_results if s.status == StepStatus.FAILED)

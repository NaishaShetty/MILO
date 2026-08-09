"""
models.py (backend/planner)

Purpose
-------
Typed data model for Phase 4 output: `PlanStep`, `Plan`, `PlanStatus`,
`StepStatus`, `ValidationIssue`, `ValidationResult`, and `PlanningResult`.
This module holds ONLY data -- no planning logic (`rule_based.py`,
`react.py`, `behavior_tree.py`), no precondition/effect logic
(`actions.py`), no validation logic (`validator.py`). It exists so every
planning strategy and every consumer of a plan (the API layer, the
evaluation framework, and eventually Phase 5) agrees on one shape,
exactly the same role `schemas/task.py` plays for Language Understanding.

Why abstract `PlanStep`s, never simulator calls
------------------------------------------------
A `PlanStep` names an *abstract* planning action (`"navigate"`,
`"pickup"`, `"open"`, ...) and a `target`/`parameters` payload -- never
an AI2-THOR action name (`MoveAhead`, `PickupObject`). This is the
architectural rule this whole phase is built around: Phase 5 owns the
translation from `PlanStep` to simulator commands, and this package
must remain usable (and testable) even in an environment where AI2-THOR
is not installed at all. See `backend/planner/__init__.py` for the full
rationale.

Design notes
------------
- Built on Pydantic (matching `schemas/task.py`'s convention) for free
  JSON (de)serialization across the API boundary and fail-fast
  validation. `extra="forbid"` everywhere, same rationale as
  `schemas/task.py`: a malformed field should fail loudly at
  construction, not be silently dropped three modules downstream.
- `Plan.metadata` and `PlanStep.parameters` are open `Dict[str, Any]`
  bags, deliberately: this project's own roadmap (memory-conditioned
  planning, scene-graph grounding, uncertainty, dynamic replanning --
  see `__init__.py`) will need to attach new, planner-specific data to
  a step or plan without a schema migration every time. Every field
  this phase actually depends on for validation/execution is still a
  typed, top-level field; `metadata`/`parameters` are the deliberate
  escape hatch, not a substitute for typing what is already known.
- `PlanStep`/`Plan` are mutable (`validate_assignment=True`, not
  frozen): a step's `status` is expected to be updated in place as
  Phase 5 executes it (`PENDING` -> `RUNNING` -> `COMPLETED`/`FAILED`),
  exactly the "aggregate root stays mutable" pattern `schemas/task.py`
  already uses for `Task`/`SingleTask`/`MultiTask`.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class StepStatus(str, Enum):
    """
    Lifecycle of one `PlanStep`. Assigned by this package as `PENDING`
    at plan-construction time; every other value is written by Phase 5
    as it executes the plan -- this package never transitions a step to
    `RUNNING`/`COMPLETED`/`FAILED` itself, since it never executes
    anything.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    # Phase 5 additions -- BLOCKED covers a step this package's own
    # docstring already anticipated Phase 5 setting ("every other value
    # is written by Phase 5 as it executes the plan"): a step whose
    # preconditions failed at execution time (as opposed to FAILED,
    # reserved for a step that was dispatched to the simulator and
    # failed there). CANCELLED covers a step never reached because
    # `execution.ExecutionController.cancel()` was called mid-plan.
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class PlanStatus(str, Enum):
    """
    Lifecycle of a whole `Plan`. `VALID`/`INVALID` are set by this
    package (via `validator.PlanValidator`); `EXECUTING`/`COMPLETED`/
    `FAILED` are Phase 5's to set once a plan is handed off. `DRAFT` is
    the transient state a plan holds between generation and validation.
    """

    DRAFT = "draft"
    VALID = "valid"
    INVALID = "invalid"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    # Phase 5 addition -- set by `execution.ExecutionController.cancel()`
    # when a caller stops an in-progress execution; see `StepStatus`'s
    # own Phase 5 additions above.
    CANCELLED = "cancelled"


class PlanStep(BaseModel):
    """
    One abstract planning action in a `Plan`.

    `action` is a lowercase snake_case name resolved against
    `actions.ACTION_REGISTRY` (e.g. `"navigate"`, `"pickup"`,
    `"open"`) -- never an AI2-THOR action name. `target` is the primary
    object/entity the action acts on; `parameters` carries any
    secondary arguments a given action needs (e.g. `place`'s
    destination container, under the key `"container"`).

    `preconditions`/`postconditions` are human-readable descriptions
    copied from the matching `actions.ActionSpec` at construction time
    (never re-derived later) so a `Plan` remains self-explanatory --
    readable and auditable -- even without cross-referencing
    `actions.py`, which is what section 8's "explainable" requirement
    is asking for.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    step_id: int = Field(
        ge=1, description="1-indexed position of this step within its Plan."
    )
    action: str = Field(
        description="Abstract planning action name, resolved against "
        "actions.ACTION_REGISTRY (e.g. 'locate', 'navigate', 'pickup', "
        "'open', 'place', 'close'). Never a simulator-specific action name."
    )
    target: Optional[str] = Field(
        default=None,
        description="Primary object/entity this action acts on, e.g. "
        "'apple'. None only for actions with no object (e.g. 'wait').",
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Secondary arguments this action needs beyond "
        "`target`, e.g. {'container': 'refrigerator'} for a 'place' step.",
    )
    description: str = Field(
        description="Short human-readable label for this step, e.g. "
        "'Navigate to apple'. Derived from action+target, used for "
        "explainability in logs, the UI, and validation error messages."
    )
    preconditions: List[str] = Field(
        default_factory=list,
        description="Human-readable preconditions that must hold in the "
        "WorldState immediately before this step executes.",
    )
    postconditions: List[str] = Field(
        default_factory=list,
        description="Human-readable facts this step guarantees to be "
        "true in the WorldState immediately after it executes.",
    )
    status: StepStatus = Field(
        default=StepStatus.PENDING,
        description="Execution lifecycle status. Always PENDING as "
        "produced by this package; Phase 5 updates it during execution.",
    )


class ValidationIssue(BaseModel):
    """
    One structured problem `validator.PlanValidator` found with a
    `Plan`. Machine-readable (`code`, `severity`, `step_id`) so a caller
    (the API layer, the UI, a test) never has to pattern-match
    `message` text to decide how to react -- `message` exists purely
    for human display.
    """

    model_config = ConfigDict(extra="forbid")

    step_id: Optional[int] = Field(
        default=None,
        description="1-indexed step this issue concerns, or None for a "
        "plan-level issue (e.g. goal never satisfied by any step).",
    )
    code: str = Field(
        description="Stable machine-readable issue code, e.g. "
        "'unknown_action', 'missing_parameter', 'precondition_failed', "
        "'duplicate_step', 'goal_not_satisfied'."
    )
    message: str = Field(description="Human-readable explanation of the issue.")
    severity: Literal["error", "warning"] = Field(
        description="'error' issues make the plan INVALID; 'warning' "
        "issues (e.g. a redundant step) do not."
    )


class ValidationResult(BaseModel):
    """
    Full report produced by one `PlanValidator.validate()` call. `valid`
    is `True` iff no issue has `severity == \"error\"` -- see
    `validator.py` for exactly which checks can raise which severity.
    """

    model_config = ConfigDict(extra="forbid")

    valid: bool
    issues: List[ValidationIssue] = Field(default_factory=list)
    goal_satisfied: Optional[bool] = Field(
        default=None,
        description="Whether the final simulated WorldState satisfies "
        "the task's goal. None when this goal has no known goal-check "
        "(see validator.py's GOAL_CHECKS) -- a plan can still be VALID "
        "with an unverifiable goal, but this is surfaced distinctly so "
        "callers can tell 'we checked and it holds' from 'we could not "
        "check'.",
    )

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity == "warning")


class Plan(BaseModel):
    """
    A complete, ordered sequence of `PlanStep`s produced by one planning
    strategy for one `SingleTask`. This -- not any planner's internal
    representation -- is the object Phase 5 is expected to consume.

    `metadata` carries planner-specific, non-essential detail (e.g. the
    ReAct planner's raw reasoning trace, the Behavior Tree planner's
    node tree, or a future memory-conditioned planner's retrieved
    context) that this package's core contract does not depend on --
    see this module's docstring on why `metadata` is an open dict.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    plan_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = Field(description="Echoes the source SingleTask.task_id.")
    planner_type: str = Field(
        description="Which planning strategy produced this plan, e.g. "
        "'rule_based', 'react', 'behavior_tree'. See factory.PlannerType."
    )
    goal_summary: Dict[str, Optional[str]] = Field(
        description="Snapshot of the task fields this plan was built "
        "from (goal/object/target/source_location/target_location), "
        "kept even if the source Task object is later mutated."
    )
    steps: List[PlanStep] = Field(default_factory=list)
    status: PlanStatus = Field(default=PlanStatus.DRAFT)
    created_at: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def step_count(self) -> int:
        return len(self.steps)


class PlanningResult(BaseModel):
    """
    The top-level return value of `Planner.plan()` -- always returned,
    never replaced by a raised exception for an ordinary "could not
    produce a usable plan" outcome (see `exceptions.py`'s docstring).

    `success` means "a Plan was generated and is VALID"; a planner that
    generates a plan which then fails validation still returns
    `success=False` with `plan` populated (so the caller can inspect
    *why* it failed) and `validation.issues` explaining the failure.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    plan: Optional[Plan] = None
    validation: Optional[ValidationResult] = None
    errors: List[str] = Field(
        default_factory=list,
        description="Top-level failure messages for cases with no Plan "
        "at all (e.g. UnsupportedGoalError was raised internally and "
        "caught at the Planner boundary) -- distinct from "
        "validation.issues, which always concerns an actual Plan.",
    )
    planner_type: str
    latency_ms: float = Field(description="Wall-clock time spent inside plan().")

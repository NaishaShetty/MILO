"""
navigation_agent.py (backend/agents)

Purpose
-------
`NavigationAgent` -- section 7.9's navigation abstraction. Unlike
every other wrapper in this package, there is no existing "Navigation"
module to wrap: low-level movement already lives inside `execution.
controller.ExecutionController`'s action dispatch (translating the
planner's abstract `"navigate"` `PlanStep` into `MoveAhead`/
`RotateLeft`/... calls), and this agent must not duplicate that (the
phase brief's explicit "should not duplicate low-level action
execution"). What it *does* own is purely interpretive: given an
`ExecutionRecord` that has already run, decide whether the failure was
navigation-related and, if so, refine the generic `agents.failures.
FailureCategory` execution already reports into the more specific
`PATH_BLOCKED` vs. `NAVIGATION_FAILURE` distinction section 7.12's
taxonomy draws -- exactly the extra context `ReflectionAgent` needs to
recommend `replan` with a useful reason ("chair blocked route", the
phase brief's own example).

Why `OBJECT_NOT_REACHABLE` becomes `PATH_BLOCKED`, not `NAVIGATION_FAILURE`
------------------------------------------------------------------------------
`execution.errors.ExecutionErrorCode.OBJECT_NOT_REACHABLE` means the
target object was resolved (it exists, in the simulator's own
metadata) but the robot could not reach it -- the most direct signal
this project's execution layer can give for "something is physically
in the way," i.e. `PATH_BLOCKED`. `NAVIGATION_FAILED` is broader (the
resolver/dispatcher itself failed to even attempt a route) and stays
`NAVIGATION_FAILURE`. `agents.failures.category_for_execution_error`
already maps both codes to the generic `NAVIGATION_FAILURE` -- this
agent is the one place that narrows `OBJECT_NOT_REACHABLE` further,
using context (the actual failing `PlanStep`) the generic mapping
function does not have.
"""

from __future__ import annotations

from typing import Optional

from agents.base import BaseAgent
from agents.contracts import AgentError, AgentRequest, AgentResponse, AgentState
from agents.failures import AgentFailure, FailureCategory
from execution.errors import ExecutionErrorCode
from execution.models import ExecutionRecord, StepStatus
from planner.state import WorldState

#: Abstract `PlanStep.action` names (see `planner/actions.py`'s
#: `ACTION_REGISTRY`) this agent treats as navigation-relevant.
_NAVIGATION_ACTIONS = frozenset({"navigate"})


class NavigationAgent(BaseAgent):
    """Interprets execution results for navigation-relevant failures. See module docstring."""

    name = "navigation"

    def current_location(self, state: WorldState) -> Optional[str]:
        return state.robot_location

    def diagnose(
        self, record: ExecutionRecord, state: WorldState
    ) -> Optional[AgentFailure]:
        """
        Returns a refined `AgentFailure` if `record`'s failing step was
        a navigation action, else `None` (not this agent's concern --
        `ReflectionAgent` falls back to `agents.execution_agent.
        ExecutionAgentWrapper.failures_from_record()`'s generic
        translation for every other kind of failure).
        """
        self._state = AgentState.ACTIVE
        try:
            failing_step = next(
                (s for s in record.step_results if s.status == StepStatus.FAILED),
                None,
            )
            if failing_step is None or failing_step.error is None:
                return None
            if failing_step.action not in _NAVIGATION_ACTIONS:
                return None

            code = failing_step.error.code
            if code == ExecutionErrorCode.OBJECT_NOT_REACHABLE:
                category = FailureCategory.PATH_BLOCKED
            elif code == ExecutionErrorCode.NAVIGATION_FAILED:
                category = FailureCategory.NAVIGATION_FAILURE
            else:
                return None

            return AgentFailure(
                category=category,
                message=failing_step.error.message,
                agent=self.name,
                recoverable=failing_step.error.recoverable,
                details={
                    "current_location": state.robot_location,
                    "target": failing_step.target,
                },
            )
        finally:
            self._state = AgentState.IDLE

    def process(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(
            request_id=request.request_id,
            success=False,
            error=AgentError(
                agent=self.name,
                message="NavigationAgent requires a typed ExecutionRecord/WorldState -- "
                "call diagnose() directly, not process().",
            ),
        )

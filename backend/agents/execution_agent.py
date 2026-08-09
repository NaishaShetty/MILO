"""
execution_agent.py (backend/agents)

Purpose
-------
`ExecutionAgentWrapper` -- the `BaseAgent` shape around `execution.
controller.ExecutionController` (section 7.10). Constructs one fresh
`ExecutionController` per `execute_plan()` call, mirroring exactly how
`orchestration.task_runner.TaskRunner`/`api/routes/execution.py`
already do it -- see `ExecutionController`'s own docstring: "Not
thread-safe for concurrent execute_plan() calls on the *same*
instance... constructs one controller per execution request." This
wrapper does not add retry/dispatch/validation logic of its own; it
adds only the translation from `execution.errors.ExecutionErrorCode`
to the shared `agents.failures.FailureCategory` a `ReflectionAgent`
reasons over (section 7.10's example: `{"action": "PickupObject",
"success": false, "error_type": "OBJECT_NOT_VISIBLE", ...}` is this
same idea -- one structured, categorized result, not a raw exception).
"""

from __future__ import annotations

from typing import List, Optional

from agents.base import BaseAgent
from agents.contracts import AgentError, AgentRequest, AgentResponse, AgentState
from agents.failures import AgentFailure, from_execution_error
from execution.controller import ExecutionController
from execution.models import ExecutionRecord, StepStatus
from planner.models import Plan
from planner.state import WorldState
from simulator.simulator import Simulator


class ExecutionAgentWrapper(BaseAgent):
    """Thin `BaseAgent` wrapper around `execution.controller.ExecutionController`.
    See module docstring."""

    name = "execution"

    def __init__(self, simulator: Optional[Simulator]) -> None:
        super().__init__()
        self._simulator = simulator
        # Set for the duration of one `execute_plan()` call so
        # `cancel_current()` (called from a *different* thread -- see
        # that method's docstring) has a live `ExecutionController` to
        # reach. Plain attribute assignment, not a lock: `execute_plan()`
        # never runs concurrently with itself on one instance (this
        # class's own "one controller per execution request" docstring
        # note), so there is exactly one writer at a time; a `cancel_
        # current()` reader racing a `None` assignment either reaches
        # the controller (cancels it) or finds `None` (nothing to
        # cancel, the run already finished) -- both are safe outcomes.
        self._active_controller: Optional[ExecutionController] = None

    def execute_plan(self, plan: Plan, state: WorldState) -> ExecutionRecord:
        self._state = AgentState.ACTIVE
        controller = ExecutionController(self._simulator)
        self._active_controller = controller
        try:
            record = controller.load_plan(plan)
            return controller.execute_plan(plan, state, record=record)
        finally:
            self._active_controller = None
            self._state = AgentState.IDLE

    def cancel_current(self) -> None:
        """
        Requests cancellation of whatever `execute_plan()` call is
        currently in flight on this instance, if any -- called from
        the API request thread handling `POST /tasks/{id}/cancel`
        while `execute_plan()` is blocked on a *different* (background)
        thread running the task itself. Reaches the live
        `ExecutionController.cancel()` (a `threading.Event`, safe to
        set cross-thread), the same mechanism `routes/execution.py::
        cancel_execution` already uses. A no-op if nothing is
        currently executing.
        """
        controller = self._active_controller
        if controller is not None:
            controller.cancel()

    @staticmethod
    def failures_from_record(record: ExecutionRecord) -> List[AgentFailure]:
        """
        Every `FAILED` step's `ExecutionError`, translated into the
        shared `AgentFailure` vocabulary -- `ReflectionAgent`'s input.
        Never fabricates a cause for a step with none recorded (mirrors
        `orchestration.task_runner.TaskRunner`'s own "never hallucinate
        a cause" rule) -- such a step is simply skipped here too.
        """
        failures: List[AgentFailure] = []
        for step in record.step_results:
            if step.status != StepStatus.FAILED or step.error is None:
                continue
            failures.append(
                from_execution_error(
                    step.error.code,
                    message=step.error.message,
                    agent="execution",
                    recoverable=step.error.recoverable,
                    details={**step.error.details, "action": step.error.action},
                )
            )
        return failures

    def process(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(
            request_id=request.request_id,
            success=False,
            error=AgentError(
                agent=self.name,
                message="ExecutionAgentWrapper requires a typed Plan/WorldState -- "
                "call execute_plan() directly, not process().",
            ),
        )

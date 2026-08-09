"""
reflection_agent.py (backend/agents)

Purpose
-------
`ReflectionAgent` -- section 7.11's post-execution reflection. Given an
already-finished `ExecutionRecord` plus the `AgentFailure`s it
produced (translated by `agents.execution_agent.ExecutionAgentWrapper.
failures_from_record()`, optionally refined by `agents.
navigation_agent.NavigationAgent.diagnose()` -- both computed by
`Orchestrator`, never imported here, per this package's "no agent
imports another agent's module" rule), decides one of `continue` /
`retry` / `replan` / `abort`, plus whether this outcome is worth a
memory write. Deterministic, rule-based -- explicitly not a second
planner (section 7.11: "Reflection should not become a second
uncontrolled planner. The Planner remains responsible for generating
plans."): every rule below inspects data, none of them constructs a
`Plan` or a `PlanStep`.

The rules, and why each exists
------------------------------------
1. `record.status == SUCCESS` -> `continue`, `store_memory=True`. The
   task worked; nothing to reflect on beyond "remember this."
2. No failure was recorded at all (a plan with zero steps, or a step
   whose `ExecutionError` was never populated) -> `abort`. Mirrors
   `orchestration.task_runner.TaskRunner`'s own "never invent a cause"
   rule -- if this agent cannot name why it failed, it cannot
   responsibly recommend retrying or replanning either.
3. `INVALID_ACTION`/`INVALID_PLAN` -> `abort` unconditionally. The plan
   itself is malformed (mirrors `execution.errors.ExecutionError.
   recoverable`'s own documented judgment that this category is never
   worth retrying) -- retrying or replanning from the exact same task
   description would just reproduce the same malformed plan.
4. Attempts exhausted (`attempt >= max_attempts`) -> `abort`. Bounded,
   same philosophy as `ExecutionController`'s own bounded per-action
   retry (this project's explicit "never create an infinite retry
   loop" rule, just one level up: bounded *replanning*, not bounded
   *dispatch*).
5. `PATH_BLOCKED`/`NAVIGATION_FAILURE`/`OBJECT_NOT_FOUND`/
   `ENVIRONMENT_CHANGED` -> `replan`. These are failures a *different
   plan* (a different route, a different target resolution) could
   plausibly resolve -- retrying the identical plan would just
   reproduce the same failure.
6. Any other `recoverable=True` failure -> `retry`. A transient
   failure (e.g. a flaky dispatch) that the *same* plan might succeed
   at on a second attempt.
7. Otherwise -> `abort`.

`store_memory` is `True` only for terminal outcomes (`continue`,
`abort`) -- `retry`/`replan` are mid-loop, and `Orchestrator` writes
exactly one memory for the whole task once it actually terminates,
matching `TaskRunner`'s existing "avoid memory pollution" policy
(never one memory per attempt).
"""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, ConfigDict

from agents.base import BaseAgent
from agents.contracts import AgentError, AgentRequest, AgentResponse
from agents.failures import AgentFailure, FailureCategory
from execution.models import ExecutionRecord, ExecutionStatus

ReflectionAction = Literal["continue", "retry", "replan", "abort"]

#: Failures a different plan could plausibly resolve -- see rule 5.
_REPLAN_CATEGORIES = frozenset(
    {
        FailureCategory.PATH_BLOCKED,
        FailureCategory.NAVIGATION_FAILURE,
        FailureCategory.OBJECT_NOT_FOUND,
        FailureCategory.ENVIRONMENT_CHANGED,
    }
)

#: Failures never worth retrying or replanning -- see rule 3.
_ABORT_CATEGORIES = frozenset(
    {FailureCategory.INVALID_ACTION, FailureCategory.INVALID_PLAN}
)


class ReflectionResult(BaseModel):
    """One reflection verdict -- section 7.11's example JSON shape."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    reason: str
    action: ReflectionAction
    store_memory: bool


class ReflectionAgent(BaseAgent):
    """Deterministic post-execution reflection. See module docstring."""

    name = "reflection"

    def reflect(
        self,
        record: ExecutionRecord,
        failures: List[AgentFailure],
        *,
        attempt: int,
        max_attempts: int,
    ) -> ReflectionResult:
        if record.status == ExecutionStatus.SUCCESS:
            return ReflectionResult(
                success=True,
                reason="task completed successfully",
                action="continue",
                store_memory=True,
            )

        if not failures:
            return ReflectionResult(
                success=False,
                reason="execution failed with no recorded cause",
                action="abort",
                store_memory=True,
            )

        primary = failures[0]

        if primary.category in _ABORT_CATEGORIES:
            return ReflectionResult(
                success=False, reason=primary.message, action="abort", store_memory=True
            )

        if attempt >= max_attempts:
            return ReflectionResult(
                success=False,
                reason=f"{primary.message} (replan attempts exhausted)",
                action="abort",
                store_memory=True,
            )

        if primary.category in _REPLAN_CATEGORIES:
            return ReflectionResult(
                success=False,
                reason=primary.message,
                action="replan",
                store_memory=False,
            )

        if primary.recoverable:
            return ReflectionResult(
                success=False,
                reason=primary.message,
                action="retry",
                store_memory=False,
            )

        return ReflectionResult(
            success=False, reason=primary.message, action="abort", store_memory=True
        )

    def process(self, request: AgentRequest) -> AgentResponse:
        return AgentResponse(
            request_id=request.request_id,
            success=False,
            error=AgentError(
                agent=self.name,
                message="ReflectionAgent requires a typed ExecutionRecord/AgentFailure "
                "list -- call reflect() directly, not process().",
            ),
        )

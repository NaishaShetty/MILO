"""
controller.py (backend/execution)

Purpose
-------
`ExecutionController` is the central Phase 5 orchestrator (section 4):
given a validated Phase 4 `planner.models.Plan`, it executes every
`PlanStep` sequentially --

```
PlanStep -> resolve objectId -> check preconditions -> dispatch
    -> validate result -> update WorldState -> update PlanStep.status
    -> next PlanStep
```

-- exactly the "Action Lifecycle" this package's own architecture
diagram (`docs/phases/phase5_execution.md`) documents, mutating the
real `Plan`/`PlanStep` objects' `status` fields in place (as
`planner.models.PlanStep`'s own docstring already anticipates: "a
step's status is expected to be updated in place as Phase 5 executes
it") while also building an independent, storage-agnostic
`execution.models.ExecutionRecord` for the API/frontend/future Memory
Agent to consume.

Why this controller never assumes a dispatched action succeeded
--------------------------------------------------------------------
Every dispatch goes through `validator.ResultValidator` before this
module ever marks a step `COMPLETED` -- section 4's explicit
requirement. A step is `FAILED` unless the simulator both reported
success AND (where this project's action vocabulary makes it
checkable) the expected ground-truth state change is present.

Why failure stops the plan instead of continuing
------------------------------------------------------
Phase 4's own action model (`planner.actions.ACTION_REGISTRY`) encodes
real causal dependencies between steps (`place` requires the object
already be held, `close` requires it already be open, ...) -- once one
step fails, every following step in a Phase-4-generated plan is
expected to fail its own precondition check anyway. This controller
therefore halts on the first unrecoverable step failure and marks every
remaining step `SKIPPED`, rather than attempting steps whose
preconditions this project already knows cannot hold -- this is
section 9's "execution stops when appropriate," not silent
partial-success reporting.

Retries, timeouts, cancellation
-----------------------------------
- **Retries** are bounded, explicit, and off by default
  (`max_step_retries=0`): when enabled, only transient-looking failures
  (`SIMULATOR_ERROR`, `NAVIGATION_FAILED`, `OBJECT_NOT_REACHABLE`,
  `ACTION_TIMEOUT`) are retried, never `INVALID_ACTION`/
  `INVALID_PARAMETER`/`PRECONDITION_FAILED`/`OBJECT_NOT_FOUND`/
  `TARGET_NOT_FOUND` (retrying those would just reproduce the same
  failure) -- and always up to a fixed ceiling, never unbounded, per
  this project's explicit "never create an infinite retry loop" rule.
  Every retry is recorded on `ActionResult.retry_count`, never hidden.
- **Timeouts** wrap each dispatched simulator call in a bounded wait
  (`step_timeout_s`, default `None` = no timeout) via a single-worker
  thread pool, so one hung AI2-THOR call cannot block execution
  indefinitely -- a timeout is reported as `ACTION_TIMEOUT`, exactly
  like any other step failure, never a hang.
- **Cancellation** is a plain `threading.Event` checked before every
  step; `cancel()` is safe to call from another thread (e.g. the API
  layer handling `POST /execution/{id}/cancel` while `execute_plan()`
  runs on a worker) and takes effect at the next step boundary --
  section 10's "execution must not continue after cancellation."
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Dict, Optional

from execution.dispatcher import ActionDispatcher
from execution.errors import ExecutionError, ExecutionErrorCode
from execution.exceptions import PlanNotExecutableError, SimulatorUnavailableError
from execution.models import (
    Action,
    ActionResult,
    ActionType,
    ExecutionEvent,
    ExecutionRecord,
    ExecutionStatus,
    StepExecutionRecord,
)
from execution.preconditions import PreconditionChecker
from execution.resolver import ObjectResolver
from execution.validator import ResultValidator
from planner.actions import get_action_spec
from planner.models import Plan, PlanStatus, PlanStep, StepStatus
from planner.state import WorldState
from simulator.simulator import Simulator

logger = logging.getLogger(__name__)

# Error codes worth a bounded retry -- see this module's docstring.
# Deliberately excludes every code that reflects a defect in the plan
# itself (INVALID_ACTION, INVALID_PARAMETER, PRECONDITION_FAILED,
# OBJECT_NOT_FOUND, TARGET_NOT_FOUND) or a terminal state
# (EXECUTION_CANCELLED) -- retrying those cannot change the outcome.
_RETRYABLE_ERROR_CODES = {
    ExecutionErrorCode.SIMULATOR_ERROR,
    ExecutionErrorCode.NAVIGATION_FAILED,
    ExecutionErrorCode.OBJECT_NOT_REACHABLE,
    ExecutionErrorCode.ACTION_TIMEOUT,
}

# `PlanStep.action` names that map to a `parameters["container"]`
# secondary target this controller must also resolve to a live
# objectId before dispatch.
_ACTIONS_WITH_CONTAINER = {"place"}

# Phase 4 abstract action name -> Phase 5 ActionType. `put_down` has no
# simulator-groundable target (AI2-THOR's PutObject always needs a
# receptacle id) -- see `_build_action`'s docstring for how it is
# reported rather than silently mis-dispatched.
_ACTION_NAME_TO_TYPE = {
    "locate": ActionType.LOCATE,
    "navigate": ActionType.NAVIGATE,
    "pickup": ActionType.PICKUP,
    "open": ActionType.OPEN,
    "close": ActionType.CLOSE,
    "place": ActionType.PUT,
}


class ExecutionController:
    """
    Executes one `Plan` at a time against one `Simulator`. Not
    thread-safe for concurrent `execute_plan()` calls on the *same*
    instance (mirrors `Simulator` itself, which owns one Unity
    subprocess) -- `api/routes/execution.py` constructs one controller
    per execution request, matching how `api/routes/planner.py`
    constructs a fresh `PlanValidator`-backed planner per request.
    """

    def __init__(
        self,
        simulator: Optional[Simulator],
        *,
        max_step_retries: int = 0,
        step_timeout_s: Optional[float] = None,
    ) -> None:
        self._simulator = simulator
        self._dispatcher = (
            ActionDispatcher(simulator) if simulator is not None else None
        )
        self._resolver = ObjectResolver()
        self._precondition_checker = PreconditionChecker()
        self._result_validator = ResultValidator()
        self._max_step_retries = max_step_retries
        self._step_timeout_s = step_timeout_s
        self._cancelled = threading.Event()

    def load_plan(self, plan: Plan) -> ExecutionRecord:
        """
        Validates that `plan` is in an executable state and builds the
        `ExecutionRecord` `execute_plan()` will fill in. Raises
        `PlanNotExecutableError` for a plan with no steps or one
        `PlanValidator` already marked `INVALID` -- executing either is
        certain to fail immediately, so this fails fast instead.
        """
        if plan.status == PlanStatus.INVALID:
            raise PlanNotExecutableError(
                f"Plan {plan.plan_id!r} is INVALID and cannot be executed."
            )
        if not plan.steps:
            raise PlanNotExecutableError(f"Plan {plan.plan_id!r} has no steps.")

        return ExecutionRecord(
            plan_id=plan.plan_id,
            task_id=plan.task_id,
            status=ExecutionStatus.PENDING,
            step_results=[
                StepExecutionRecord(
                    step_id=step.step_id,
                    action=step.action,
                    target=step.target,
                    status=StepStatus.PENDING,
                )
                for step in plan.steps
            ],
        )

    def cancel(self) -> None:
        """Requests cancellation; takes effect at the next step boundary."""
        self._cancelled.set()

    def stop(self) -> None:
        """Alias for `cancel()` -- section 10's `stop` control surface."""
        self.cancel()

    def execute_plan(
        self,
        plan: Plan,
        world_state: Optional[WorldState] = None,
        *,
        record: Optional[ExecutionRecord] = None,
    ) -> ExecutionRecord:
        """
        Executes every step of `plan` in order against a fresh (or
        caller-supplied) `WorldState`, mutating `plan`/its `PlanStep`s
        in place and returning the full `ExecutionRecord`. Always
        returns a record -- even a cancelled or fully-failed run -- and
        never raises for an ordinary step failure, matching
        `Planner.plan()`'s own "always return a result" convention.

        `record`, if given, must be one this controller's own
        `load_plan(plan)` already produced (e.g. `api/routes/execution.py`
        calls `load_plan()` synchronously to hand a caller back an
        `execution_id` immediately, then runs this method on a
        background thread against that *same* record object so a
        concurrent `GET /execution/{id}` sees live progress rather than
        a second, disconnected record).
        """
        record = record if record is not None else self.load_plan(plan)
        # Deliberately does NOT clear `self._cancelled` here: a caller
        # that calls `cancel()` before -- or concurrently with, from
        # another thread -- this method must still see the run come
        # back CANCELLED. Each `ExecutionController` is meant to drive
        # exactly one execution (see this class's own docstring), so
        # there is no "stale cancellation from a previous run" case to
        # guard against; a fresh instance's `_cancelled` is simply
        # never set until `cancel()` is called.
        state = world_state if world_state is not None else WorldState.initial()

        record.status = ExecutionStatus.RUNNING
        record.started_at = time.time()
        plan.status = PlanStatus.EXECUTING
        logger.info(
            "execution.plan_started",
            extra={"plan_id": plan.plan_id, "execution_id": record.execution_id},
        )

        halted = False
        for step in plan.steps:
            step_result = next(
                s for s in record.step_results if s.step_id == step.step_id
            )

            if self._cancelled.is_set():
                step.status = StepStatus.CANCELLED
                step_result.status = StepStatus.CANCELLED
                self._emit(record, step, "cancelled")
                halted = True
                continue

            if halted:
                step.status = StepStatus.SKIPPED
                step_result.status = StepStatus.SKIPPED
                self._emit(record, step, "skipped")
                continue

            result = self.execute_step(plan, step, state, record)
            if not result.success:
                halted = True

        record.finished_at = time.time()
        unresolved = any(
            s.status in (StepStatus.FAILED, StepStatus.BLOCKED)
            for s in record.step_results
        )
        if self._cancelled.is_set():
            record.status = ExecutionStatus.CANCELLED
            plan.status = PlanStatus.CANCELLED
        elif unresolved:
            record.status = ExecutionStatus.FAILED
            plan.status = PlanStatus.FAILED
        else:
            record.status = ExecutionStatus.SUCCESS
            plan.status = PlanStatus.COMPLETED

        logger.info(
            "execution.plan_finished",
            extra={
                "plan_id": plan.plan_id,
                "execution_id": record.execution_id,
                "status": record.status.value,
                "duration_ms": record.duration_ms,
            },
        )
        return record

    def execute_step(
        self, plan: Plan, step: PlanStep, state: WorldState, record: ExecutionRecord
    ) -> ActionResult:
        """
        Executes exactly one `PlanStep`: resolve -> check preconditions
        -> dispatch (with bounded retry/timeout) -> validate -> update
        `WorldState`/`PlanStep.status`. Always returns an `ActionResult`
        (constructing a synthetic failed one for a precondition
        rejection, which never reaches the dispatcher at all).
        """
        step.status = StepStatus.RUNNING
        step_result = next(s for s in record.step_results if s.step_id == step.step_id)
        step_result.status = StepStatus.RUNNING
        self._emit(record, step, "started")

        if self._simulator is None or self._dispatcher is None:
            raise SimulatorUnavailableError(
                "ExecutionController has no Simulator configured/started."
            )

        metadata = self._simulator.get_metadata()
        object_id = self._resolver.resolve(step.target, metadata)
        container_id = (
            self._resolver.resolve(step.parameters.get("container"), metadata)
            if step.action in _ACTIONS_WITH_CONTAINER
            else None
        )

        check = self._precondition_checker.check(
            step,
            state,
            resolved_object_id=object_id,
            resolved_container_id=container_id,
        )
        if not check.satisfied:
            error = ExecutionError(
                code=check.error_code or ExecutionErrorCode.PRECONDITION_FAILED,
                message=check.message or "Precondition check failed.",
                step_id=step.step_id,
                action=step.action,
                recoverable=False,
            )
            step.status = StepStatus.BLOCKED
            step_result.status = StepStatus.BLOCKED
            step_result.error = error
            record.error = record.error or error
            self._emit(record, step, "blocked", error=error)
            logger.warning(
                "execution.step_blocked",
                extra={
                    "plan_id": plan.plan_id,
                    "step_id": step.step_id,
                    "action": step.action,
                    "error_code": error.code.value,
                },
            )
            return ActionResult(
                success=False,
                action=step.action,
                action_id="",
                step_id=step.step_id,
                error=error.message,
                error_code=error.code,
                metadata={},
            )

        action = self._build_action(step, object_id, container_id)
        result = self._dispatch_with_retries(action)
        step_result.result = result

        if result.success:
            step.status = StepStatus.COMPLETED
            step_result.status = StepStatus.COMPLETED
            spec = get_action_spec(step.action)
            if spec is not None:
                spec.apply_effect(state, step.target, step.parameters)
            self._emit(record, step, "success", result=result)
            logger.info(
                "execution.step_succeeded",
                extra={
                    "plan_id": plan.plan_id,
                    "step_id": step.step_id,
                    "action": step.action,
                    "duration_ms": result.duration_ms,
                },
            )
        else:
            error = ExecutionError(
                code=result.error_code or ExecutionErrorCode.UNKNOWN_ERROR,
                message=result.error or "Action failed with no further detail.",
                step_id=step.step_id,
                action=step.action,
                recoverable=(result.error_code in _RETRYABLE_ERROR_CODES),
                details=dict(result.metadata),
            )
            step.status = StepStatus.FAILED
            step_result.status = StepStatus.FAILED
            step_result.error = error
            record.error = record.error or error
            self._emit(record, step, "failed", result=result, error=error)
            logger.warning(
                "execution.step_failed",
                extra={
                    "plan_id": plan.plan_id,
                    "step_id": step.step_id,
                    "action": step.action,
                    "error_code": error.code.value,
                },
            )

        return result

    def _build_action(
        self, step: PlanStep, object_id: Optional[str], container_id: Optional[str]
    ) -> Action:
        action_type = _ACTION_NAME_TO_TYPE.get(step.action, ActionType.LOCATE)
        parameters: Dict[str, Any] = {}
        if object_id is not None:
            parameters["object_id"] = object_id
        if container_id is not None:
            parameters["container_id"] = container_id
        return Action(
            action_type=action_type, parameters=parameters, step_id=step.step_id
        )

    def _dispatch_with_retries(self, action: Action) -> ActionResult:
        attempt = 0
        while True:
            start = time.time()
            try:
                raw_result = self._dispatch_with_timeout(action)
            except FutureTimeoutError:
                result = ActionResult(
                    success=False,
                    action=action.action_type.value,
                    action_id=action.action_id,
                    step_id=action.step_id,
                    object_id=action.parameters.get("object_id"),
                    target_id=action.parameters.get("container_id"),
                    error=f"Action {action.action_type.value!r} exceeded its "
                    f"{self._step_timeout_s}s timeout.",
                    error_code=ExecutionErrorCode.ACTION_TIMEOUT,
                    duration_ms=(time.time() - start) * 1000,
                    retry_count=attempt,
                )
            except (ValueError, AttributeError) as exc:
                # A malformed Action (missing parameter) or a Simulator
                # call this dispatcher/simulator combination cannot
                # actually serve -- never propagated as an unhandled
                # 500, always reported as structured failure data.
                result = ActionResult(
                    success=False,
                    action=action.action_type.value,
                    action_id=action.action_id,
                    step_id=action.step_id,
                    object_id=action.parameters.get("object_id"),
                    target_id=action.parameters.get("container_id"),
                    error=str(exc),
                    error_code=ExecutionErrorCode.INVALID_PARAMETER,
                    duration_ms=(time.time() - start) * 1000,
                    retry_count=attempt,
                )
            except Exception as exc:
                # Deliberately broad: any unexpected simulator-side exception
                # must become structured failure data, never an unhandled
                # crash of the execution loop.
                result = ActionResult(
                    success=False,
                    action=action.action_type.value,
                    action_id=action.action_id,
                    step_id=action.step_id,
                    object_id=action.parameters.get("object_id"),
                    target_id=action.parameters.get("container_id"),
                    error=str(exc),
                    error_code=ExecutionErrorCode.SIMULATOR_ERROR,
                    duration_ms=(time.time() - start) * 1000,
                    retry_count=attempt,
                )
            else:
                duration_ms = (time.time() - start) * 1000
                result = self._result_validator.validate(
                    action, raw_result, duration_ms=duration_ms, retry_count=attempt
                )

            if result.success or attempt >= self._max_step_retries:
                return result
            if result.error_code not in _RETRYABLE_ERROR_CODES:
                return result
            attempt += 1
            logger.info(
                "execution.step_retrying",
                extra={
                    "action": action.action_type.value,
                    "attempt": attempt,
                    "error_code": (
                        result.error_code.value if result.error_code else None
                    ),
                },
            )

    def _dispatch_with_timeout(self, action: Action) -> Optional[Any]:
        assert self._dispatcher is not None
        if self._step_timeout_s is None:
            return self._dispatcher.dispatch(action)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self._dispatcher.dispatch, action)
            return future.result(timeout=self._step_timeout_s)

    def _emit(
        self,
        record: ExecutionRecord,
        step: PlanStep,
        status: str,
        *,
        result: Optional[ActionResult] = None,
        error: Optional[ExecutionError] = None,
    ) -> None:
        event = ExecutionEvent(
            execution_id=record.execution_id,
            plan_id=record.plan_id,
            step_id=step.step_id,
            action=step.action,
            target=step.target,
            status=status,
            duration_ms=result.duration_ms if result is not None else None,
            error_code=error.code if error is not None else None,
            message=error.message if error is not None else None,
        )
        record.events.append(event)

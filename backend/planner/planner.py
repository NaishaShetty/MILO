"""
planner.py (backend/planner)

Purpose
-------
Defines `Planner`, the common abstract interface every planning
strategy (`RuleBasedPlanner`, `ReActPlanner`, `BehaviorTreePlanner`,
and any future strategy) implements. Keeping this interface independent
of any one strategy's internals is what lets `factory.create_planner()`
hand back any of them interchangeably, and what lets
`evaluation.PlannerEvaluator` compare them on equal footing -- the rest
of the system (the API layer, the Phase 5/6.3 integration) is written
against `Planner.plan()` and `PlanningResult`, never against a concrete
subclass.

The template method: `plan()` vs. `_generate_steps()`
-------------------------------------------------------
Every strategy needs the same bookkeeping around its actual planning
logic: start a timer, log start/success/failure, run the resulting
`Plan` through `validator.PlanValidator`, and package everything into a
`PlanningResult`. Duplicating that in every strategy would be exactly
the kind of drift this project's engineering principles warn against.
`Planner.plan()` is a template method that owns all of that; a
subclass implements `_generate_steps(task, state, memory_context) ->
List[PlanStep]` and raises a `planner.exceptions.PlanningError`
subclass if it cannot produce steps at all (e.g.
`UnsupportedGoalError`). `ReActPlanner` overrides `plan()` entirely
instead (see `react.py`) because its control flow interleaves
generation and validation per-step rather than generating a complete
plan up front -- `Planner` permits this by making `plan()` itself
overridable, while still exposing `_finalize()` as a protected helper
so `ReActPlanner` does not have to re-implement the shared bookkeeping
either.

Phase 6.3: `memory_context` -- an optional, structured input, never
hidden state
------------------------------------------------------------------------
`plan()`/`_generate_steps()` accept an optional `memory.agent.
PlannerMemoryContext` (default `None`, so every pre-6.3 call site --
18 in this repository's own test suite, plus `api/routes/planner.py`
-- keeps working unmodified). This package still never imports
`memory.retrieval`/`memory.manager`/`sqlite3` -- only the one small,
already-computed `PlannerMemoryContext` type from `memory.agent`, which
this package treats as opaque, read-only, structured data (a list of
already-ranked `memory.retrieval.MemoryResult`s plus the query that
produced them), exactly the section 6/7 requirement: "the planner must
not directly reach into the storage layer; memory should be a
contextual input, not hidden global state." Only `RuleBasedPlanner`
(`rule_based.py`) actually reasons over it as of Phase 6.3 --
`BehaviorTreePlanner`/`ReActPlanner` accept and forward it for
interface consistency (see each module's own docstring on why they do
not yet consume it themselves).
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar, List, Optional

from planner.exceptions import PlanningError
from planner.models import Plan, PlanningResult, PlanStep
from planner.state import WorldState
from planner.validator import PlanValidator
from schemas.task import SingleTask

if TYPE_CHECKING:  # pragma: no cover
    from memory.agent import PlannerMemoryContext

logger = logging.getLogger(__name__)


class Planner(ABC):
    """
    Common interface for every planning strategy. See this module's
    docstring for the template-method contract between `plan()` and
    `_generate_steps()`, and for the Phase 6.3 `memory_context`
    parameter.
    """

    #: Stable identifier stored on every `Plan.planner_type` /
    #: `PlanningResult.planner_type` this strategy produces. Overridden
    #: by each concrete subclass; also the value `factory.PlannerType`
    #: maps to a constructor.
    planner_type: ClassVar[str] = "base"

    def __init__(self, validator: Optional[PlanValidator] = None) -> None:
        self._validator = validator or PlanValidator()

    def plan(
        self,
        task: SingleTask,
        state: WorldState,
        memory_context: "Optional[PlannerMemoryContext]" = None,
    ) -> PlanningResult:
        """
        Runs this strategy end to end: generate steps, wrap them in a
        `Plan`, validate, and return a `PlanningResult`. See this
        module's docstring for why this is a template method rather
        than logic every subclass repeats, and for `memory_context`.
        """
        started_at = time.monotonic()
        logger.info(
            "planner.plan.start",
            extra={
                "planner_type": self.planner_type,
                "task_id": task.task_id,
                "goal": task.goal,
                "memory_context_count": (
                    len(memory_context.results) if memory_context else 0
                ),
            },
        )
        try:
            steps = self._generate_steps(task, state, memory_context)
        except PlanningError as exc:
            elapsed_ms = (time.monotonic() - started_at) * 1000.0
            logger.warning(
                "planner.plan.failed",
                extra={
                    "planner_type": self.planner_type,
                    "task_id": task.task_id,
                    "error": str(exc),
                },
            )
            return PlanningResult(
                success=False,
                plan=None,
                validation=None,
                errors=[str(exc)],
                planner_type=self.planner_type,
                latency_ms=elapsed_ms,
            )
        return self._finalize(task, state, steps, started_at, memory_context)

    @abstractmethod
    def _generate_steps(
        self,
        task: SingleTask,
        state: WorldState,
        memory_context: "Optional[PlannerMemoryContext]" = None,
    ) -> List[PlanStep]:
        """
        Produces the ordered `PlanStep`s for `task`, given the current
        `state` and, optionally, retrieved memory context. Must raise a
        `planner.exceptions.PlanningError` subclass (never a bare
        exception) if no steps can be produced. A subclass that does
        not (yet) reason over `memory_context` must still accept the
        parameter (even if unused) -- see this module's docstring.
        """
        raise NotImplementedError

    def _finalize(
        self,
        task: SingleTask,
        state: WorldState,
        steps: List[PlanStep],
        started_at: float,
        memory_context: "Optional[PlannerMemoryContext]" = None,
    ) -> PlanningResult:
        """
        Shared "wrap steps into a validated Plan" logic, exposed as a
        protected helper so `ReActPlanner` (which does not implement
        `_generate_steps`, see `react.py`) can still reuse it.
        `memory_context`, when given, is attached to `Plan.
        metadata["memory_context"]` as a small summary (query + memory
        ids/count, never the full memory content) -- `Plan.metadata`'s
        own docstring already anticipated exactly this ("a future
        memory-conditioned planner's retrieved context"), so a plan is
        self-explanatory about what memory query informed it without
        this package needing a new typed `Plan` field.
        """
        plan = Plan(
            task_id=task.task_id or "",
            planner_type=self.planner_type,
            goal_summary={
                "goal": task.goal,
                "object": task.object,
                "target": task.target,
                "source_location": task.source_location,
                "target_location": task.target_location,
            },
            steps=steps,
        )
        if memory_context is not None:
            plan.metadata["memory_context"] = memory_context.summary()
        logger.info(
            "planner.plan.generated",
            extra={
                "planner_type": self.planner_type,
                "task_id": task.task_id,
                "step_count": len(steps),
            },
        )

        logger.info(
            "planner.plan.validating", extra={"planner_type": self.planner_type}
        )
        validation = self._validator.validate(plan, task, state)
        elapsed_ms = (time.monotonic() - started_at) * 1000.0
        logger.info(
            "planner.plan.validated" if validation.valid else "planner.plan.invalid",
            extra={
                "planner_type": self.planner_type,
                "task_id": task.task_id,
                "valid": validation.valid,
                "error_count": validation.error_count,
                "latency_ms": elapsed_ms,
            },
        )
        return PlanningResult(
            success=validation.valid,
            plan=plan,
            validation=validation,
            errors=[],
            planner_type=self.planner_type,
            latency_ms=elapsed_ms,
        )

"""
evaluation.py (backend/planner)

Purpose
-------
Implements `PlannerEvaluator`, the comparison layer section 13 asks
for: run one or more `planner.Planner` strategies against the same
`SingleTask`/`state.WorldState` and collect the metrics needed to
compare them -- success, validity, latency, step count, invalid-action
count, redundant-step count, and goal satisfaction -- without ever
touching AI2-THOR. Every number here comes from a real `PlanningResult`
produced by an actual planner run; this module never fabricates a
metric (see section 17's "DO NOT fabricate performance numbers").

Why this belongs in `backend/planner/`, not `backend/evaluation/`
----------------------------------------------------------------------
`backend/evaluation/` (Phase 3.6) benchmarks the *Language* runtime
(LLM provider/prompt comparison) and depends on Language-specific types
(`RuntimeMetadata`, dataset loaders for instruction/label pairs) this
package has no use for. Planner evaluation instead only needs a
`Planner` and a `SingleTask` it already has in-process -- no dataset
loader, no benchmark-run persistence layer exists for it yet. Keeping
this module here avoids a premature dependency between the two
evaluation concerns; a future harness that *does* want to persist
planner benchmark runs (mirroring `backend/evaluation/result_store.py`)
can be layered on top of `PlannerMetrics` without this module needing
to change.

What this enables later
------------------------
`PlannerMetrics` is intentionally the unit both an ad hoc comparison
(`compare()`) and a future large-scale experiment (Experiment 1 --
Rule-based vs ReAct vs Behavior Tree; Experiment 6 -- latency vs task
complexity, see `__init__.py`'s roadmap) can be built from without a
schema change: every field already present is what those experiments
need to aggregate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from planner.models import PlanningResult
from planner.planner import Planner
from planner.state import WorldState
from schemas.task import SingleTask


@dataclass
class PlannerMetrics:
    """One planner's measured performance on one task."""

    planner_type: str
    success: bool
    valid: bool
    goal_satisfied: Optional[bool]
    latency_ms: float
    step_count: int
    invalid_action_count: int
    redundant_step_count: int
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "planner_type": self.planner_type,
            "success": self.success,
            "valid": self.valid,
            "goal_satisfied": self.goal_satisfied,
            "latency_ms": round(self.latency_ms, 3),
            "step_count": self.step_count,
            "invalid_action_count": self.invalid_action_count,
            "redundant_step_count": self.redundant_step_count,
            "error": self.error,
        }


class PlannerEvaluator:
    """
    Runs one or more planners against the same task/state and reports
    `PlannerMetrics` for each -- entirely in-process, entirely
    simulator-free (see this module's docstring).
    """

    def evaluate(
        self, planner: Planner, task: SingleTask, state: WorldState
    ) -> PlannerMetrics:
        """Runs one planner once and extracts its metrics from the resulting PlanningResult."""
        result = planner.plan(task, state.clone())
        return self._metrics_from_result(planner.planner_type, result)

    def compare(
        self, planners: Dict[str, Planner], task: SingleTask, state: WorldState
    ) -> List[PlannerMetrics]:
        """
        Evaluates every planner in `planners` (keyed by a caller-chosen
        label, typically matching `factory.PlannerType.value`) against
        an identical starting `state`, cloned per-run so no planner's
        simulation leaks into another's.
        """
        return [self.evaluate(planner, task, state) for planner in planners.values()]

    @staticmethod
    def _metrics_from_result(
        planner_type: str, result: PlanningResult
    ) -> PlannerMetrics:
        plan = result.plan
        validation = result.validation
        invalid_action_count = (
            sum(1 for i in validation.issues if i.severity == "error")
            if validation
            else 0
        )
        redundant_step_count = (
            sum(1 for i in validation.issues if i.code == "duplicate_step")
            if validation
            else 0
        )
        error = result.errors[0] if result.errors else None
        return PlannerMetrics(
            planner_type=planner_type,
            success=result.success,
            valid=bool(validation.valid) if validation else False,
            goal_satisfied=validation.goal_satisfied if validation else None,
            latency_ms=result.latency_ms,
            step_count=plan.step_count if plan else 0,
            invalid_action_count=invalid_action_count,
            redundant_step_count=redundant_step_count,
            error=error,
        )

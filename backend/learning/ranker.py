"""
ranker.py (backend/learning)

Plan ranking behind its own flag (`MILO_PLAN_RANKING=1`): when more than one
planner can produce a valid plan for a task, score each plan by the product of
the predictor's P(step succeeds) over its steps and keep the best.

Each step is scored against the *current* simulator state (the state before the
plan runs) -- an approximation for later steps, whose state the plan itself
will change; the plan score is therefore a relative ranking signal, not a
calibrated mission-success probability. Ties go to the first (default)
planner, so with no signal MILO plans exactly as before.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from learning.predictor_features import context_from_live
from learning.serving import OutcomePredictor
from planner.models import Plan, PlanningResult

logger = logging.getLogger(__name__)


def score_plan(
    plan: Plan,
    predictor: OutcomePredictor,
    metadata: Optional[Mapping[str, Any]],
    planner: str,
) -> float:
    """Product of predicted step success probabilities (1.0 for an empty plan)."""
    score = 1.0
    n = len(plan.steps)
    for i, step in enumerate(plan.steps):
        ctx = context_from_live(
            action=step.action,
            target=step.target,
            metadata=dict(metadata or {}),
            step_index=i,
            remaining_steps=n - i - 1,
            retries_so_far=0,
            replans_so_far=0,
            planner=planner,
        )
        score *= predictor.predict(ctx).p_success
    return score


class PlanRanker:
    def __init__(
        self,
        predictor: OutcomePredictor,
        planner_names: Sequence[str] = ("rule_based", "htn", "behavior_tree"),
        world_model: Optional[Any] = None,
    ):
        #: Optional `learning.worldmodel.WorldModel`: score plans by rolling the
        #: predicted state forward instead of against the starting state.
        self._world = world_model
        self._predictor = predictor
        self._names = list(planner_names)

    def best(
        self,
        candidates: Sequence[PlanningResult],
        metadata: Optional[Mapping[str, Any]],
    ) -> PlanningResult:
        """The highest-scoring valid candidate (first one if none can be scored)."""
        valid = [c for c in candidates if c.success and c.plan is not None]
        if len(valid) < 2 or not self._predictor.usable:
            return candidates[0]
        scored: List[Any] = []
        for c in valid:
            assert c.plan is not None
            scored.append((self._score(c.plan, metadata, c.planner_type), c))
        top = max(scored, key=lambda t: t[0])  # max() keeps the first on ties
        ranking: Dict[str, float] = {c.planner_type: round(s, 4) for s, c in scored}
        assert top[1].plan is not None
        top[1].plan.metadata["ranking"] = {
            "scores": ranking,
            "chosen": top[1].planner_type,
        }
        return top[1]

    def _score(self, plan: Plan, metadata, planner: str) -> float:
        if self._world is not None:
            try:
                from learning.worldmodel import rollout_score

                return rollout_score(
                    plan, self._predictor, self._world, metadata, planner
                )
            except Exception:
                logger.warning("ranker.rollout_failed", exc_info=True)
        return score_plan(plan, self._predictor, metadata, planner)

    @property
    def planner_names(self) -> List[str]:
        return list(self._names)


_ = Callable  # typing helper kept for callers

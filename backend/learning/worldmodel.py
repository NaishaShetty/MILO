"""
worldmodel.py (backend/learning)

A small learned *transition model* of the symbolic world MILO already logs: given the
step's context (the same `featurize()` vector the outcome predictor uses) it predicts
what the target looks like after the step -- visible, reachable, open, switched on --
and whether the hand will be holding something.

Why: `ranker.score_plan` scores every step of a plan against the state *before the plan
runs*, so a `pick_up` that follows a `navigate` is judged as if the robot were still far
away. `rollout_score` applies the transition model step by step so later steps are
scored against the state the earlier steps are expected to leave behind.

Trees (scikit-learn HistGradientBoosting), one per field. Behind `MILO_WORLD_MODEL=1`
(needs `MILO_PLAN_RANKING=1`); a missing/failed model means the old static scoring.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from learning.predictor_features import context_from_live, featurize
from learning.serving import OutcomePredictor
from planner.models import Plan

logger = logging.getLogger(__name__)

#: field -> column in the dataset (`a_<field>`); `held` is reduced to "holding something".
FIELDS = ["visible", "reachable", "is_open", "is_on", "holding"]


def after_targets(row: Mapping[str, Any]) -> Dict[str, int]:
    """The transition model's labels from a dataset row's `a_*` columns."""

    def num(key: str) -> int:
        v = row.get(key)
        return -1 if v is None or v == "" else int(float(str(v)))

    return {
        "visible": num("a_visible"),
        "reachable": num("a_reachable"),
        "is_open": num("a_is_open"),
        "is_on": num("a_is_on"),
        "holding": int((row.get("a_held") or "none") != "none"),
    }


def before_state(row: Mapping[str, Any]) -> Dict[str, int]:
    """What 'nothing changes' would predict (the baseline)."""

    def num(key: str) -> int:
        v = row.get(key)
        return -1 if v is None or v == "" else int(float(str(v)))

    return {
        "visible": num("b_visible"),
        "reachable": num("b_reachable"),
        "is_open": num("b_is_open"),
        "is_on": num("b_is_on"),
        "holding": int((row.get("b_held") or "none") != "none"),
    }


class WorldModel:
    def __init__(self, models: Dict[str, Any]) -> None:
        self._models = models

    @classmethod
    def fit(
        cls, contexts: Sequence[Mapping[str, Any]], targets: Sequence[Dict[str, int]]
    ) -> "WorldModel":
        x = np.array([featurize(c) for c in contexts], dtype=np.float64)
        models: Dict[str, Any] = {}
        for f in FIELDS:
            y = np.array([t[f] for t in targets])
            if len(set(y.tolist())) < 2:
                models[f] = int(y[0])  # constant field
            else:
                models[f] = HistGradientBoostingClassifier(
                    max_iter=120, random_state=0
                ).fit(x, y)
        return cls(models)

    def predict(self, ctx: Mapping[str, Any]) -> Dict[str, int]:
        x = np.array([featurize(ctx)], dtype=np.float64)
        out: Dict[str, int] = {}
        for f, m in self._models.items():
            out[f] = m if isinstance(m, int) else int(m.predict(x)[0])
        return out

    def predict_many(
        self, contexts: Sequence[Mapping[str, Any]]
    ) -> List[Dict[str, int]]:
        x = np.array([featurize(c) for c in contexts], dtype=np.float64)
        cols = {
            f: (np.full(len(x), m) if isinstance(m, int) else m.predict(x))
            for f, m in self._models.items()
        }
        return [{f: int(cols[f][i]) for f in cols} for i in range(len(x))]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pickle.dumps(self._models))

    @classmethod
    def load(cls, path: Path) -> Optional["WorldModel"]:
        try:
            return cls(pickle.loads(Path(path).read_bytes()))
        except Exception:
            logger.warning("world_model.load_failed", exc_info=True)
            return None


def rollout_score(
    plan: Plan,
    predictor: OutcomePredictor,
    world: WorldModel,
    metadata: Optional[Mapping[str, Any]],
    planner: str,
) -> float:
    """Product of P(step succeeds), each step scored against the state the earlier steps
    are predicted to leave behind (target facts and what the hand holds)."""
    score = 1.0
    n = len(plan.steps)
    state: Dict[str, Dict[str, int]] = {}  # per-target overrides from earlier steps
    holding: Optional[bool] = None
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
        key = (step.target or "").lower()
        seen = state.get(key)
        if seen:
            for f in ("visible", "reachable", "is_open", "is_on"):
                ctx[f] = seen[f]
            ctx["target_found"] = 1
        if holding is not None:
            ctx["held"] = (ctx["object_class"] if holding else "none") or "none"
        score *= predictor.predict(ctx).p_success
        after = world.predict(ctx)
        state[key] = {f: after[f] for f in ("visible", "reachable", "is_open", "is_on")}
        holding = bool(after["holding"])
    return score

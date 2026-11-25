"""Phase F: learned transition model + rollout-aware plan scoring."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from learning.config import learning_kwargs
from learning.ranker import PlanRanker, score_plan
from learning.worldmodel import (
    FIELDS,
    WorldModel,
    after_targets,
    before_state,
    rollout_score,
)

BASE = {
    "action": "navigate",
    "object_class": "mug",
    "target_found": 1,
    "visible": 1,
    "distance": 3.0,
    "reachable": 0,
    "is_open": -1,
    "is_on": -1,
    "held": "none",
}


def _rows():
    contexts, targets = [], []
    for i in range(300):
        nav = i % 2 == 0
        contexts.append(
            {
                **BASE,
                "action": "navigate" if nav else "pickup",
                "reachable": 0 if nav else 1,
                "distance": 3.0 if nav else 1.0,
            }
        )
        targets.append(
            {
                "visible": 1,
                "reachable": 1,
                "is_open": -1,
                "is_on": -1,
                "holding": 0 if nav else 1,
            }
        )
    return contexts, targets


def test_after_targets_and_before_state_read_dataset_columns():
    row = {
        "a_visible": "1",
        "a_reachable": "0",
        "a_is_open": "",
        "a_is_on": "1",
        "a_held": "mug",
        "b_visible": "1",
        "b_reachable": "1",
        "b_is_open": "0",
        "b_is_on": "-1",
        "b_held": "none",
    }
    assert after_targets(row) == {
        "visible": 1,
        "reachable": 0,
        "is_open": -1,
        "is_on": 1,
        "holding": 1,
    }
    assert before_state(row)["holding"] == 0 and before_state(row)["is_open"] == 0


def test_model_learns_that_picking_up_leaves_the_hand_full(tmp_path):
    contexts, targets = _rows()
    model = WorldModel.fit(contexts, targets)
    assert (
        model.predict({**BASE, "action": "pickup", "reachable": 1, "distance": 1.0})[
            "holding"
        ]
        == 1
    )
    assert model.predict(BASE)["holding"] == 0
    assert set(model.predict(BASE)) == set(FIELDS)
    assert [
        m["holding"]
        for m in model.predict_many(
            [BASE, {**BASE, "action": "pickup", "reachable": 1, "distance": 1.0}]
        )
    ] == [0, 1]
    model.save(tmp_path / "w.pkl")
    assert WorldModel.load(tmp_path / "w.pkl").predict(BASE) == model.predict(BASE)
    assert WorldModel.load(tmp_path / "missing.pkl") is None


class _Pred:
    """P(success) is high only when the target is reachable (like the real predictor)."""

    usable = True

    def predict(self, ctx):
        return SimpleNamespace(p_success=0.9 if ctx["reachable"] else 0.1)


def _plan():
    return SimpleNamespace(
        steps=[
            SimpleNamespace(action="navigate", target="mug"),
            SimpleNamespace(action="pickup", target="mug"),
        ],
        metadata={},
    )


def test_rollout_scores_later_steps_against_the_predicted_state(monkeypatch):
    contexts, targets = _rows()
    model = WorldModel.fit(contexts, targets)
    monkeypatch.setattr(
        "learning.worldmodel.context_from_live",
        lambda **kw: {**BASE, "action": kw["action"], "reachable": 0},
    )
    monkeypatch.setattr(
        "learning.ranker.context_from_live",
        lambda **kw: {**BASE, "action": kw["action"], "reachable": 0},
    )
    static = score_plan(_plan(), _Pred(), {}, "rule_based")
    rolled = rollout_score(_plan(), _Pred(), model, {}, "rule_based")
    assert static == pytest.approx(0.01)  # both steps judged from the far-away start
    assert rolled == pytest.approx(
        0.1 * 0.9
    )  # pickup judged after the predicted navigate


def test_ranker_falls_back_to_static_scoring_if_the_rollout_fails():
    class Broken:
        def predict(self, ctx):
            raise RuntimeError("boom")

    ranker = PlanRanker(_Pred(), world_model=Broken())
    plan = _plan()
    cands = [
        SimpleNamespace(success=True, plan=plan, planner_type=n) for n in ("a", "b")
    ]
    # static scoring runs (and the ranker still returns a candidate)
    assert ranker.best(cands, {}) in cands


def test_flag_off_by_default_and_missing_model_means_static(monkeypatch, tmp_path):
    monkeypatch.setenv("MILO_PLAN_RANKING", "1")
    monkeypatch.delenv("MILO_WORLD_MODEL", raising=False)
    monkeypatch.setenv("MILO_MODEL_DIR", str(tmp_path / "none"))
    assert learning_kwargs() == {}  # no outcome model at all -> rule-based behaviour

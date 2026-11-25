"""Phase B: outcome predictor features, training, serving fallbacks, learned reflector, ranker."""

from __future__ import annotations

import json
import pickle
from types import SimpleNamespace

import numpy as np
import pytest

from agents.reflection_agent import ReflectionAgent
from execution.errors import ExecutionError, ExecutionErrorCode
from execution.models import (
    ExecutionRecord,
    ExecutionStatus,
    StepExecutionRecord,
    StepStatus,
)
from learning import config as learning_config
from learning.build_dataset import build
from learning.features import world_features
from learning.generate import generate, run_episode
from learning.metrics import binary_report, ece, reliability_curve
from learning.predictor_features import (
    FEATURE_NAMES,
    context_from_live,
    context_from_row,
    featurize,
)
from learning.ranker import PlanRanker, score_plan
from learning.reflector import LearnedReflector
from learning.serving import OutcomePredictor, Prediction, load_predictor
from learning.synthetic import SyntheticSimulator, make_scene
from learning.train_outcome import retry_labels, train
from planner.models import Plan, PlanningResult, PlanStep

# -- feature parity (training vs serving) ---------------------------------------


def _live_and_row():
    meta = SyntheticSimulator(make_scene("scene_p", 0)).get_metadata()
    target = next(o["objectType"] for o in meta["objects"] if o.get("pickupable"))
    live = context_from_live(
        action="pickup",
        target=target,
        metadata=meta,
        step_index=2,
        remaining_steps=3,
        retries_so_far=1,
        replans_so_far=0,
        planner="htn",
        memory_stats={"hits": 2, "sim_max": 0.7, "sim_mean": 0.5, "prior_success": 1.0},
        perception_conf=0.8,
    )
    world = world_features(meta, target)
    row = {  # exactly what the dataset builder writes for this step
        "action": "pickup",
        "target": target.lower(),
        "planner": "htn",
        "b_object_class": world["object_class"],
        "b_target_found": world["target_found"],
        "b_visible": world["visible"],
        "b_distance": world["distance"],
        "b_reachable": world["reachable"],
        "b_is_open": world["is_open"],
        "b_is_on": world["is_on"],
        "b_held": world["held"],
        "retries_so_far": 1,
        "replans_so_far": 0,
        "step_index": 2,
        "remaining_steps": 3,
        "memory_hits": 2,
        "memory_sim_max": 0.7,
        "memory_sim_mean": 0.5,
        "memory_prior_success": 1.0,
        "perception_conf": 0.8,
    }
    return live, row


def test_training_and_serving_feature_paths_match():
    live, row = _live_and_row()
    assert featurize(context_from_row(row)) == featurize(live)
    assert len(featurize(live)) == len(FEATURE_NAMES)


def test_features_never_look_at_the_outcome_of_the_step():
    _, row = _live_and_row()
    leaky = dict(
        row,
        a_reachable=0,
        a_held="apple",
        success="1",
        failure_type="blocked",
        duration_ms=9999,
    )
    assert featurize(context_from_row(leaky)) == featurize(context_from_row(row))


def test_unknown_object_classes_do_not_crash():
    vec = featurize({"action": "pickup", "object_class": "zebra", "held": "narwhal"})
    assert len(vec) == len(FEATURE_NAMES)


# -- metrics --------------------------------------------------------------------


def test_ece_is_zero_for_perfect_calibration_and_large_for_overconfidence():
    y = np.array([1] * 90 + [0] * 10)
    assert ece(y, np.full(100, 0.9)) < 1e-9
    assert ece(y, np.full(100, 0.5)) > 0.35
    assert reliability_curve(y, np.full(100, 0.9))[0]["count"] == 100
    assert 0 <= binary_report(y, np.full(100, 0.9))["brier"] <= 1


# -- training + serving on a small dataset -----------------------------------------


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    root = tmp_path_factory.mktemp("outcome")
    generate(root / "eps", episodes=900, scenes=20, seed=5, workers=1, batch=100)
    build(root / "eps", root / "data", seed=0)
    metrics = train(root / "data", root / "models", registry=root / "registry.json")
    return root, metrics


def test_training_beats_both_baselines_on_held_out_scenes(trained):
    _, m = trained
    assert m["trees"]["auroc"] > m["baseline_rules"]["auroc"] + 0.1
    assert m["trees"]["brier"] < m["baseline_majority"]["brier"]
    assert m["trees"]["ece"] < 0.05
    assert (
        m["failure_type"]["accuracy"] > m["failure_type"]["baseline_majority_accuracy"]
    )
    assert m["duration"]["mae_ms"] < m["duration"]["baseline_mean_mae_ms"]
    assert "mlp" in m and isinstance(m["mlp_kept"], bool)


def test_registry_records_the_run(trained):
    root, m = trained
    reg = json.loads((root / "registry.json").read_text())["models"][-1]
    assert reg["name"] == "outcome_predictor" and reg["data_hash"] and reg["date"]
    assert reg["metrics"]["auroc"] == m["trees"]["auroc"]


def test_retry_labels_mark_failures_that_later_succeeded():
    rows = [
        {
            "episode_id": "e",
            "attempt": "0",
            "action": "pickup",
            "target": "apple",
            "success": "0",
        },
        {
            "episode_id": "e",
            "attempt": "1",
            "action": "pickup",
            "target": "apple",
            "success": "1",
        },
        {
            "episode_id": "f",
            "attempt": "0",
            "action": "open",
            "target": "fridge",
            "success": "0",
        },
    ]
    assert retry_labels(rows) == {0: 1, 2: 0}


def test_served_predictions_are_fast_calibrated_numbers(trained):
    root, _ = trained
    predictor = load_predictor(root / "models")
    assert predictor is not None
    ctx, _ = _live_and_row()
    pred = predictor.predict(ctx, explain=True)
    assert 0.0 <= pred.p_success <= 1.0 and 0.0 <= pred.p_retry_success <= 1.0
    assert pred.latency_ms < 20 and pred.version == predictor.version
    assert abs(sum(pred.failure_probs.values()) - 1.0) < 1e-6
    # An out-of-reach pickup is predicted far worse than one within reach.
    near = dict(ctx, reachable=1, distance=0.8, visible=1)
    far = dict(ctx, reachable=0, distance=3.0, visible=1)
    assert predictor.predict(near).p_success > predictor.predict(far).p_success + 0.3


# -- regression tests for each fallback path -----------------------------------------


def test_missing_model_falls_back_to_none(tmp_path):
    assert load_predictor(tmp_path / "nope") is None
    assert load_predictor(None) is None


def test_corrupt_model_file_falls_back_to_none(tmp_path):
    (tmp_path / "v1").mkdir()
    (tmp_path / "v1" / "model.pkl").write_bytes(b"not a pickle")
    assert load_predictor(tmp_path) is None


def test_flags_off_or_model_missing_change_nothing(tmp_path):
    assert learning_config.learning_kwargs({}) == {}
    env = {"MILO_LEARNED_REFLECTOR": "on", "MILO_MODEL_DIR": str(tmp_path / "none")}
    assert learning_config.learning_kwargs(env) == {}
    assert learning_config.reflector_mode({"MILO_LEARNED_REFLECTOR": "bogus"}) == "off"


def test_flags_build_the_learned_components(trained):
    root, _ = trained
    env = {
        "MILO_LEARNED_REFLECTOR": "shadow",
        "MILO_PLAN_RANKING": "1",
        "MILO_MODEL_DIR": str(root / "models"),
    }
    kwargs = learning_config.learning_kwargs(env)
    assert (
        isinstance(kwargs["reflection_agent"], LearnedReflector)
        and kwargs["reflection_agent"].mode == "shadow"
    )
    assert (
        isinstance(kwargs["plan_ranker"], PlanRanker) and "outcome_predictor" in kwargs
    )


def _artifact(trained):
    root, _ = trained
    path = sorted((root / "models").iterdir())[-1] / "model.pkl"
    return pickle.load(open(path, "rb"))


def test_a_slow_predictor_disables_itself(trained):
    p = OutcomePredictor(_artifact(trained), budget_ms=0.0001, max_slow=2)
    ctx, _ = _live_and_row()
    p.predict(ctx)
    p.predict(ctx)
    assert not p.usable and "too slow" in (p.disabled_reason or "")


def test_drifted_inputs_make_the_predictor_unusable(trained):
    p = OutcomePredictor(_artifact(trained), drift_threshold=0.5)
    weird = {
        "action": "pickup",
        "object_class": "zebra",
        "distance": 500.0,
        "step_index": 90,
        "remaining_steps": 90,
        "retries_so_far": 40,
    }
    for _ in range(12):
        p.predict(weird)
    assert p.drifted and not p.usable


# -- the learned reflector ---------------------------------------------------------------


class StubPredictor:
    thresholds = {"retry": 0.5, "abort": 0.2}
    disabled_reason = None
    usable = True

    def __init__(self, p_success=0.1, p_retry=0.9, kind="timeout", confident=True):
        self.p = (p_success, p_retry, kind, confident)

    def predict(self, ctx, explain=False):
        p, r, kind, conf = self.p
        return Prediction(
            p,
            r,
            100.0,
            {kind: 1.0},
            0.1,
            "stub",
            conf,
            ["whether it is within reach (hurts)"],
        )


def _failed_record(code=ExecutionErrorCode.NAVIGATION_FAILED, target="fridge"):
    err = ExecutionError(
        code=code,
        message="path blocked",
        step_id=1,
        action="navigate",
        recoverable=False,
    )
    return ExecutionRecord(
        plan_id="p",
        task_id="t",
        status=ExecutionStatus.FAILED,
        step_results=[
            StepExecutionRecord(
                step_id=1,
                action="navigate",
                target=target,
                status=StepStatus.FAILED,
                error=err,
            )
        ],
    )


def _failures():
    from agents.failures import from_execution_error

    return [
        from_execution_error(
            ExecutionErrorCode.NAVIGATION_FAILED,
            message="path blocked",
            agent="execution",
            recoverable=False,
            details={},
        )
    ]


CTX = {1: {"action": "navigate", "object_class": "fridge", "replans_so_far": 0}}


def _reflect(mode, predictor, record=None, attempt=0):
    r = LearnedReflector(ReflectionAgent(), predictor, mode=mode)
    result = r.reflect(
        record or _failed_record(),
        _failures(),
        attempt=attempt,
        max_attempts=2,
        contexts=CTX,
    )
    return r, result


def test_shadow_mode_keeps_the_rule_based_verdict_but_logs_the_learned_one():
    r, result = _reflect("shadow", StubPredictor(p_retry=0.9))
    assert result.action == "replan"  # rule-based: navigation failure -> replan
    d = r.pop_decisions()[0]
    assert (
        d["rule_based"] == "replan"
        and d["learned"] == "retry"
        and d["agree"] is False
        and d["used"] is False
    )
    assert d["prediction"]["version"] == "stub"
    assert r.pop_decisions() == []


def test_on_mode_uses_the_learned_verdict_with_a_plain_explanation():
    _, result = _reflect("on", StubPredictor(p_retry=0.9))
    assert result.action == "retry" and "second time" in result.explanation


def test_learned_replan_when_retry_is_unlikely_to_help():
    _, result = _reflect("on", StubPredictor(p_retry=0.05, kind="blocked"))
    assert result.action == "replan" and "new plan" in result.explanation


def test_early_abort_when_the_object_cannot_be_found_explains_itself():
    _, result = _reflect(
        "on", StubPredictor(p_success=0.01, p_retry=0.02, kind="wrong_object")
    )
    assert result.action == "abort"
    assert "can't find the fridge anywhere I can see" in result.explanation


def test_a_successful_mission_is_never_second_guessed():
    ok = ExecutionRecord(
        plan_id="p", task_id="t", status=ExecutionStatus.SUCCESS, step_results=[]
    )
    r = LearnedReflector(
        ReflectionAgent(), StubPredictor(p_retry=0.0, kind="wrong_object"), mode="on"
    )
    assert (
        r.reflect(ok, [], attempt=0, max_attempts=2, contexts=CTX).action == "continue"
    )
    assert r.decisions == []


def test_low_confidence_defers_to_the_rule_based_verdict():
    r, result = _reflect("on", StubPredictor(p_retry=0.9, confident=False))
    assert result.action == "replan" and r.pop_decisions()[0]["used"] is False


def test_an_unusable_predictor_defers_to_the_rule_based_verdict():
    stub = StubPredictor(p_retry=0.9)
    stub.usable = False
    stub.disabled_reason = "too slow"
    r, result = _reflect("on", stub)
    assert result.action == "replan"
    assert r.pop_decisions()[0]["fallback_reason"] == "too slow"


def test_off_mode_and_missing_contexts_are_pure_passthrough():
    assert _reflect("off", StubPredictor())[1].action == "replan"
    r = LearnedReflector(ReflectionAgent(), StubPredictor(), mode="on")
    assert (
        r.reflect(_failed_record(), _failures(), attempt=0, max_attempts=2).action
        == "replan"
    )


def test_exhausted_budget_keeps_the_rule_based_abort():
    _, result = _reflect("on", StubPredictor(p_retry=0.9), attempt=2)
    assert result.action == "abort" and result.explanation is None


# -- plan ranking ----------------------------------------------------------------------------


def _plan(planner, *actions):
    steps = [
        PlanStep(step_id=i + 1, action=a, target="apple", description=a)
        for i, a in enumerate(actions)
    ]
    return PlanningResult(
        success=True,
        plan=Plan(task_id="t", planner_type=planner, goal_summary={}, steps=steps),
        validation=None,
        errors=[],
        planner_type=planner,
        latency_ms=0,
    )


class ByAction:
    usable = True

    def predict(self, ctx, explain=False):
        p = {"locate": 0.99, "navigate": 0.9, "pickup": 0.7}[ctx["action"]]
        return SimpleNamespace(p_success=p)


def test_plans_are_scored_by_the_product_of_step_probabilities():
    plan = _plan("htn", "locate", "navigate", "pickup").plan
    assert score_plan(plan, ByAction(), {}, "htn") == pytest.approx(0.99 * 0.9 * 0.7)


def test_ranking_picks_the_highest_scoring_plan_and_ties_keep_the_default():
    ranker = PlanRanker(ByAction())
    long_plan, short_plan = _plan("rule_based", "locate", "navigate", "pickup"), _plan(
        "htn", "locate", "pickup"
    )
    best = ranker.best([long_plan, short_plan], {})
    assert (
        best.planner_type == "htn" and best.plan.metadata["ranking"]["chosen"] == "htn"
    )
    same = ranker.best([_plan("rule_based", "locate"), _plan("htn", "locate")], {})
    assert same.planner_type == "rule_based"
    assert ranker.best([long_plan], {}) is long_plan


# -- end to end: learned vs rule-based on fixed seeds ----------------------------------------


def test_the_online_comparison_is_reproducible_and_learned_is_no_worse_in_shadow(
    trained,
):
    from learning.eval_online import run_one, summarise

    root, _ = trained
    predictor = load_predictor(root / "models")
    rows = {
        m: [run_one(i, f"scene_{i % 5}", m, predictor, seed=1) for i in range(40)]
        for m in ("rule", "shadow")
    }
    again = [run_one(i, f"scene_{i % 5}", "rule", predictor, seed=1) for i in range(40)]

    def key(rs):
        return [(r["success"], r["replans"], round(r["time_s"], 3)) for r in rs]

    assert key(rows["rule"]) == key(again)  # fixed seeds -> identical results
    assert key(rows["rule"]) == key(rows["shadow"])  # shadow never changes behaviour
    assert summarise(rows["rule"])["episodes"] == 40


def test_the_logger_records_model_decisions_for_later_training(trained, tmp_path):
    root, _ = trained
    import sqlite3
    from contextlib import closing

    # An episode run with the shadow reflector: decisions land in the step rows.
    from agents.execution_agent import ExecutionAgentWrapper
    from agents.planner_agent import PlannerAgentWrapper
    from learning.episode_log import EpisodeLogger
    from learning.synthetic import Faults
    from orchestration.orchestrator import Orchestrator
    from planner.factory import create_planner
    from schemas.task import SingleTask

    predictor = load_predictor(root / "models")
    scene = make_scene("scene_m", 0)
    item = next(o["objectType"].lower() for o in scene if o.get("pickupable"))
    sim = SyntheticSimulator(scene, Faults("blocked_path", item, times=1))
    db = tmp_path / "log.db"
    orch = Orchestrator(
        PlannerAgentWrapper(create_planner("rule_based")),
        ExecutionAgentWrapper(sim),  # type: ignore[arg-type]
        reflection_agent=LearnedReflector(ReflectionAgent(), predictor, mode="shadow"),
        outcome_predictor=predictor,
        episode_logger=EpisodeLogger(db),
    )
    state = orch.run(SingleTask(goal="pick_up", object=item))
    with closing(sqlite3.connect(db)) as conn:
        logged = [
            r[0]
            for r in conn.execute(
                "SELECT model_decisions FROM steps WHERE model_decisions IS NOT NULL"
            )
        ]
    assert logged and json.loads(logged[0])[0]["model"] == "outcome_predictor"
    # Every step got a confidence for the UI.
    assert all(
        s.confidence is not None
        for s in state.current_plan.steps
        if s.status.value == "completed"
    )
    _ = run_episode


# -- promotion and rollback ----------------------------------------------------------------


def test_promotion_requires_a_win_and_keeps_the_previous_for_rollback(
    trained, tmp_path
):
    from learning.promote import promote, rollback, wins

    root, _ = trained
    out = tmp_path / "models"
    first = promote(root / "data", out)
    assert first["promoted"] and (out / "current.json").exists()
    assert load_predictor(out).version == first["in_service"]
    second = promote(root / "data", out)  # identical data: no real win -> not promoted
    assert not second["promoted"] and second["in_service"] == first["in_service"]
    assert wins({"auroc": 0.97, "ece": 0.01}, {"auroc": 0.95, "ece": 0.01})
    assert not wins({"auroc": 0.97, "ece": 0.2}, {"auroc": 0.95, "ece": 0.01})
    assert rollback(out) is None  # nothing earlier than the first promotion


# -- Lab: models panel and toggle ---------------------------------------------------------------


def test_lab_models_panel_and_runtime_toggle(trained, monkeypatch):
    from fastapi.testclient import TestClient

    from api.app import app
    from api.routes.tasks import _store, build_orchestrator
    from tests._execution_test_helpers import FakeSimulator

    root, _ = trained
    monkeypatch.setenv("MILO_MODEL_DIR", str(root / "models"))
    build_orchestrator(FakeSimulator(objects=[]))
    try:
        with TestClient(app) as client:
            panel = client.get("/api/v1/lab/models").json()["models"][0]
            assert (
                panel["name"] == "outcome_predictor"
                and panel["mode"] == "off"
                and panel["available"]
            )
            assert (
                panel["metrics"]["ece"] < 0.05
                and "falls back to the rules" in panel["explains"]
            )

            on = client.post(
                "/api/v1/lab/models/outcome_predictor", json={"mode": "shadow"}
            ).json()
            assert on["result"]["mode"] == "shadow"
            assert (
                on["models"][0]["mode"] == "shadow"
                and on["models"][0]["healthy"] is True
            )
            off = client.post(
                "/api/v1/lab/models/outcome_predictor", json={"mode": "off"}
            ).json()
            assert off["models"][0]["mode"] == "off"
            bad = client.post(
                "/api/v1/lab/models/outcome_predictor", json={"mode": "maybe"}
            )
            assert bad.status_code == 422
    finally:
        _store._orchestrator = None


def test_toggle_without_a_model_stays_off_with_a_plain_reason(tmp_path, monkeypatch):
    from agents.execution_agent import ExecutionAgentWrapper
    from agents.planner_agent import PlannerAgentWrapper
    from learning.config import set_reflector_mode
    from orchestration.orchestrator import Orchestrator
    from planner.factory import create_planner
    from tests._execution_test_helpers import FakeSimulator

    orch = Orchestrator(
        PlannerAgentWrapper(create_planner("rule_based")),
        ExecutionAgentWrapper(FakeSimulator()),
    )
    result = set_reflector_mode(
        orch, "on", {"MILO_MODEL_DIR": str(tmp_path / "missing")}
    )
    assert result["mode"] == "off" and "built-in rules" in result["reason"]

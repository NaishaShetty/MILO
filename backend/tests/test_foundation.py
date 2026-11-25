"""Roadmap 2, Phase 1: action registry, success predicates, trace log."""

from __future__ import annotations

import sqlite3

import numpy as np
import pytest

from agents.execution_agent import ExecutionAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from execution.controller import _ACTION_NAME_TO_TYPE
from execution.models import ActionType
from learning.synthetic import Faults, SyntheticSimulator
from orchestration.orchestrator import Orchestrator
from planner.actions import ACTION_REGISTRY, executable_actions
from planner.factory import create_planner
from schemas.task import SingleTask
from tracelog.recorder import TraceRecorder, build_recorder, thumbnail
from tracelog.store import KINDS, SCHEMA_VERSION, SchemaMismatch, TraceStore
from verification.predicates import (
    Predicate,
    check_all,
    goal_predicates,
)

# -- action registry --------------------------------------------------------------


def test_every_executable_registry_action_maps_to_a_real_executor_action():
    assert set(executable_actions()) == set(_ACTION_NAME_TO_TYPE)
    assert "act" not in executable_actions()
    for name in ("navigate", "pickup", "place", "open", "close", "turn_on",
                 "turn_off", "push", "put_down", "look_around", "locate"):  # fmt: skip
        assert name in executable_actions()


def test_registry_entries_are_typed_with_preconditions_and_effects():
    for name, spec in ACTION_REGISTRY.items():
        assert spec.name == name
        assert isinstance(spec.arguments, dict)
        if spec.requires_target:
            assert spec.arguments.get("target"), name
    assert ACTION_REGISTRY["place"].arguments == {
        "target": "object",
        "container": "receptacle",
    }
    assert [p.code for p in ACTION_REGISTRY["push"].preconditions] == [
        "target_near",
        "hand_empty",
    ]


def test_new_executor_actions_exist():
    assert {ActionType.DROP, ActionType.PUSH, ActionType.LOOK_AROUND} <= set(ActionType)


# -- success predicates ---------------------------------------------------------------

META = {
    "objects": [
        {"objectId": "Mug|1", "objectType": "Mug", "visible": True, "distance": 1.0,
         "parentReceptacles": ["Shelf|1"]},
        {"objectId": "Shelf|1", "objectType": "Shelf", "visible": True, "distance": 1.2},
        {"objectId": "Fridge|1", "objectType": "Fridge", "visible": True, "distance": 3.0,
         "isOpen": False},
        {"objectId": "Faucet|1", "objectType": "Faucet", "visible": False, "distance": 2.0,
         "isToggled": True},
        {"objectId": "Apple|1", "objectType": "Apple", "visible": True, "distance": 0.5},
    ],
    "inventoryObjects": [{"objectId": "Apple|1", "objectType": "Apple"}],
}  # fmt: skip


@pytest.mark.parametrize(
    "pred, ok",
    [
        (Predicate("held", "apple"), True),
        (Predicate("held", "mug"), False),
        (Predicate("hand_empty"), False),
        (Predicate("in_receptacle", "mug", "shelf"), True),
        (Predicate("in_receptacle", "mug", "fridge"), False),
        (Predicate("is_closed", "fridge"), True),
        (Predicate("is_open", "fridge"), False),
        (Predicate("toggled_on", "faucet"), True),
        (Predicate("toggled_off", "faucet"), False),
        (Predicate("visible", "faucet"), False),
        (Predicate("near", "mug"), True),
        (Predicate("near", "fridge"), False),
    ],
)
def test_predicates_read_simulator_metadata(pred, ok):
    result = pred.check(META)
    assert result.ok is ok
    assert (result.reason == "") is ok


def test_predicates_explain_failures_and_handle_missing_objects():
    assert "can't find the book" in Predicate("visible", "book").check(META).reason
    assert "can't open or close" in Predicate("is_open", "mug").check(META).reason
    assert Predicate("hand_empty").check({}).ok
    with pytest.raises(ValueError):
        Predicate("teleported", "mug")
    with pytest.raises(ValueError):
        Predicate("in_receptacle", "mug")


def test_predicates_round_trip_through_json():
    p = Predicate("in_receptacle", "mug", "shelf")
    assert Predicate.from_dict(p.to_dict()) == p
    assert check_all([p], META)[0].to_dict()["text"] == "the mug is in/on the shelf"


def test_goal_predicates_for_the_task_library():
    def kinds(**kw):
        return [(p.kind, p.object) for p in goal_predicates(SingleTask(**kw))]

    assert kinds(goal="fetch", object="mug") == [("held", "mug")]
    assert kinds(goal="store", object="mug", target="fridge") == [
        ("in_receptacle", "mug"),
        ("hand_empty", None),
    ]
    assert kinds(goal="open", object="fridge") == [("is_open", "fridge")]
    assert kinds(goal="turn_off", object="faucet") == [("toggled_off", "faucet")]
    assert kinds(goal="tidy_up") == []


# -- trace store schema ------------------------------------------------------------------


def test_trace_store_schema_round_trip_and_version_guard(tmp_path):
    store = TraceStore(tmp_path / "t.db")
    store.begin(
        "m1", task_text="fetch the mug", parsed_task={"goal": "fetch"}, planner="htn"
    )
    store.add("m1", "plan", {"steps": 3})
    store.add("m1", "step", {"action": "pickup"}, step_id=2)
    store.finish(
        "m1", "succeeded", latencies={"total_ms": 5.0}, verification=[{"ok": True}]
    )
    trace = store.get("m1")
    assert trace["mission"]["outcome"] == "succeeded"
    assert trace["mission"]["schema_version"] == SCHEMA_VERSION
    assert [r["kind"] for r in trace["records"]] == ["plan", "step"]
    assert trace["records"][1]["step_id"] == 2
    assert store.list()[0]["mission_id"] == "m1"
    assert store.get("nope") is None
    with pytest.raises(ValueError):
        store.add("m1", "gossip", {})
    with sqlite3.connect(tmp_path / "t.db") as db:
        db.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
    with pytest.raises(SchemaMismatch):
        TraceStore(tmp_path / "t.db")


def test_thumbnail_and_recorder_flag(monkeypatch, tmp_path):
    assert thumbnail(None) is None
    assert isinstance(thumbnail(np.zeros((48, 64, 3), dtype=np.uint8)), str)
    monkeypatch.setenv("MILO_TRACE", "0")
    assert build_recorder() is None
    monkeypatch.setenv("MILO_TRACE", "1")
    monkeypatch.setenv("MILO_TRACE_DB", str(tmp_path / "x.db"))
    assert isinstance(build_recorder(), TraceRecorder)


# -- a mission produces a complete trace ----------------------------------------------------


def _scene():
    return [
        {"objectId": "Mug|1", "objectType": "Mug", "distance": 2.0, "visible": True,
         "pickupable": True, "parentReceptacles": ["Table|1"]},
        {"objectId": "Table|1", "objectType": "Table", "distance": 2.0, "visible": True,
         "pickupable": False},
        {"objectId": "Fridge|1", "objectType": "Fridge", "distance": 3.0, "visible": True,
         "pickupable": False, "openable": True, "isOpen": False},
    ]  # fmt: skip


def _run(task, tmp_path, frames=None):
    store = TraceStore(tmp_path / "trace.db")
    sim = SyntheticSimulator(_scene(), Faults())
    orch = Orchestrator(
        PlannerAgentWrapper(create_planner("rule_based")),
        ExecutionAgentWrapper(sim),  # type: ignore[arg-type]
        trace_recorder=TraceRecorder(store, frame_source=frames),
    )
    state = orch.run(task)
    return state, store.get(state.task_id)


def test_a_mission_produces_a_complete_trace(tmp_path):
    frame = np.full((30, 40, 3), 200, dtype=np.uint8)
    state, trace = _run(
        SingleTask(goal="store", object="mug", target="fridge"), tmp_path, lambda: frame
    )
    assert state.status.value == "succeeded"
    kinds = [r["kind"] for r in trace["records"]]
    assert kinds[0] == "mission_started" and kinds[-1] == "mission_finished"
    for needed in ("plan", "step", "thought", "reflection", "verification"):
        assert needed in kinds, needed
    assert set(kinds) <= set(KINDS)
    steps = [r for r in trace["records"] if r["kind"] == "step"]
    assert len(steps) == len(state.current_plan.steps)
    for s in steps:
        d = s["data"]
        assert d["status"] in ("success", "already_done")
        assert d["duration_ms"] is not None and d["frame"]
        assert "planning_ms" in d["stage_ms"]
    reflection = next(r for r in trace["records"] if r["kind"] == "reflection")
    assert reflection["data"]["verdict"] == "continue"
    mission = trace["mission"]
    assert mission["outcome"] == "succeeded" and mission["latencies"]["total_ms"] > 0
    assert all(v["ok"] for v in mission["verification"])
    assert {v["kind"] for v in mission["verification"]} == {
        "in_receptacle",
        "hand_empty",
    }


def test_a_failed_mission_is_traced_with_its_reason(tmp_path):
    state, trace = _run(SingleTask(goal="clean", object="mug"), tmp_path)
    assert state.status.value == "failed"
    assert trace["mission"]["outcome"] == "failed"
    assert "I don't have a way to do 'clean' yet" in trace["mission"]["reason"]


def test_enforced_goal_check_fails_a_mission_the_world_contradicts(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("MILO_GOAL_CHECK", "enforce")

    class Liar(SyntheticSimulator):
        def put_object(self, object_id):  # reports success, changes nothing
            self.inventory_objects = []
            return self._event(True)

    store = TraceStore(tmp_path / "t.db")
    orch = Orchestrator(
        PlannerAgentWrapper(create_planner("rule_based")),
        ExecutionAgentWrapper(Liar(_scene(), Faults())),  # type: ignore[arg-type]
        trace_recorder=TraceRecorder(store),
    )
    state = orch.run(SingleTask(goal="store", object="mug", target="fridge"))
    assert state.status.value == "failed"
    assert "not in/on the fridge" in store.get(state.task_id)["mission"]["reason"]

    monkeypatch.setenv("MILO_GOAL_CHECK", "report")  # default: record, don't fail
    orch2 = Orchestrator(
        PlannerAgentWrapper(create_planner("rule_based")),
        ExecutionAgentWrapper(Liar(_scene(), Faults())),  # type: ignore[arg-type]
    )
    state2 = orch2.run(SingleTask(goal="store", object="mug", target="fridge"))
    assert state2.status.value == "succeeded"
    assert any(not v["ok"] for v in state2.verification)


def test_a_broken_trace_store_never_breaks_a_mission(tmp_path):
    class Broken(TraceRecorder):
        def __init__(self):
            pass

        def _on_event(self, *a, **k):
            raise RuntimeError("disk full")

        def _on_step(self, *a, **k):
            raise RuntimeError("disk full")

    orch = Orchestrator(
        PlannerAgentWrapper(create_planner("rule_based")),
        ExecutionAgentWrapper(SyntheticSimulator(_scene(), Faults())),  # type: ignore[arg-type]
        trace_recorder=Broken(),
    )
    assert orch.run(SingleTask(goal="fetch", object="mug")).status.value == "succeeded"


def test_trace_api_lists_and_returns_missions(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from api.app import app

    store = TraceStore(tmp_path / "api.db")
    store.begin("abc", task_text="fetch the mug")
    store.add("abc", "plan", {"steps": 1})
    store.finish("abc", "succeeded")
    monkeypatch.setenv("MILO_TRACE_DB", str(tmp_path / "api.db"))
    client = TestClient(app)
    assert client.get("/api/v1/traces").json()["missions"][0]["mission_id"] == "abc"
    assert client.get("/api/v1/traces/abc").json()["records"][0]["kind"] == "plan"
    assert client.get("/api/v1/traces/zzz").status_code == 404

"""Roadmap 2, Phase 4: ask before guessing, approve risky steps, preview plans, undo."""

from __future__ import annotations

import threading
import time

import pytest

from agents.execution_agent import ExecutionAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from learning.synthetic import Faults, SyntheticSimulator
from novel.eval_novel import P, S, into, plan, scene
from novel.planner import NovelPlanner
from novel.providers import ScriptedProvider
from novel.safety import Constraints
from novel.skills import SkillLibrary
from orchestration.explain import _the
from orchestration.orchestrator import Orchestrator
from oversight.ambiguity import display_name, where_to, which_one
from oversight.gate import ApprovalGate, Decision
from oversight.undo import FixedPlanner, inverse_plan
from planner.factory import create_planner
from schemas.task import SingleTask


def two_cups():
    objs = scene()
    objs.append({"objectId": "Cup|2", "objectType": "Cup", "distance": 3.3, "visible": True,
                 "pickupable": True, "parentReceptacles": ["Table|1"]})  # fmt: skip
    return objs


def _meta(objs):
    return SyntheticSimulator(objs, Faults()).get_metadata()


# -- ask before guessing ------------------------------------------------------------------


def test_two_matching_cups_produce_one_question_with_choices():
    q = which_one(
        SingleTask(goal="fetch", object="cup"), "bring me the cup", _meta(two_cups())
    )
    assert (
        q["kind"] == "clarify"
        and q["message"] == "I can see 2 cups. Which one do you mean?"
    )
    assert [c["label"] for c in q["choices"]] == [
        "the cup on the shelf",
        "the cup on the table",
    ]
    assert {c["object_id"] for c in q["choices"]} == {"Cup|1", "Cup|2"}
    assert all(c["instruction"] == "bring me the cup" for c in q["choices"])


def test_no_question_when_only_one_matches_or_it_is_already_pinned():
    assert (
        which_one(
            SingleTask(goal="fetch", object="mug"), "bring the mug", _meta(two_cups())
        )
        is None
    )
    assert (
        which_one(SingleTask(goal="fetch", object="Cup|2"), "x", _meta(two_cups()))
        is None
    )


def test_where_to_lists_places_with_the_right_preposition():
    labels = {c["label"] for c in where_to("mug", _meta(scene()))}
    assert {"in the fridge", "on the table", "on the shelf"} <= labels
    assert not any("apple" in label or "faucet" in label for label in labels)


def test_pinned_ids_read_as_plain_names():
    assert display_name("Cup|2") == "cup" and _the("Cup|2") == "the cup"


# -- the risk gate -------------------------------------------------------------------------


def _run_with_gate(task, objs, gate, planner="rule_based"):
    sim = SyntheticSimulator(objs, Faults())
    orch = Orchestrator(
        PlannerAgentWrapper(create_planner(planner)),
        ExecutionAgentWrapper(sim),  # type: ignore[arg-type]
        approval_gate=gate,
    )
    box = {}
    thread = threading.Thread(target=lambda: box.setdefault("state", orch.run(task)))
    thread.start()
    return orch, sim, thread, box


def _wait_for_question(orch, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        st = orch._current_state
        if st is not None and st.pending_decision:
            return st
        time.sleep(0.01)
    raise AssertionError("MILO never asked")


def _dangerous_scene():
    objs = scene()
    objs.append({"objectId": "Toaster|1", "objectType": "Toaster", "distance": 2.0, "visible": True,
                 "pickupable": False, "isToggled": False})  # fmt: skip
    return objs


def test_a_risky_step_waits_for_approval_then_runs():
    gate = ApprovalGate(timeout_s=10)
    orch, sim, thread, box = _run_with_gate(
        SingleTask(goal="turn_on", object="toaster"), _dangerous_scene(), gate
    )
    st = _wait_for_question(orch)
    q = st.pending_decision
    assert q["kind"] == "step" and q["action"] == "turn_on" and "dangerous" in q["why"]
    toaster = next(o for o in sim.objects if o["objectType"] == "Toaster")
    assert toaster["isToggled"] is False  # nothing happened while waiting
    assert gate.decide(st.task_id, Decision("approve"))
    thread.join(5)
    assert box["state"].status.value == "succeeded" and toaster["isToggled"] is True
    assert box["state"].pending_decision is None


def test_a_skipped_risky_step_never_runs():
    gate = ApprovalGate(timeout_s=10)
    orch, sim, thread, box = _run_with_gate(
        SingleTask(goal="turn_on", object="toaster"), _dangerous_scene(), gate
    )
    st = _wait_for_question(orch)
    gate.decide(st.task_id, Decision("skip"))
    thread.join(5)
    toaster = next(o for o in sim.objects if o["objectType"] == "Toaster")
    assert toaster["isToggled"] is False
    assert any("leave that step out" in t["text"] for t in box["state"].thoughts)


def test_no_answer_means_skip_never_go_ahead():
    gate = ApprovalGate(timeout_s=0.2)
    orch, sim, thread, box = _run_with_gate(
        SingleTask(goal="turn_on", object="toaster"), _dangerous_scene(), gate
    )
    thread.join(5)
    toaster = next(o for o in sim.objects if o["objectType"] == "Toaster")
    assert toaster["isToggled"] is False


def test_ordinary_steps_are_never_held_up():
    gate = ApprovalGate(timeout_s=10)
    orch, sim, thread, box = _run_with_gate(
        SingleTask(goal="place", object="mug", target="shelf"), scene(), gate
    )
    thread.join(5)
    assert box["state"].status.value == "succeeded"


def test_cancel_releases_a_waiting_question():
    gate = ApprovalGate(timeout_s=30)
    orch, sim, thread, box = _run_with_gate(
        SingleTask(goal="turn_on", object="toaster"), _dangerous_scene(), gate
    )
    _wait_for_question(orch)
    orch.cancel()
    thread.join(5)
    assert not thread.is_alive()
    assert box["state"].status.value in ("cancelled", "failed")


# -- plan preview for plans MILO worked out itself ----------------------------------------------


def _novel_run(gate, tmp_path, table):
    sim = SyntheticSimulator(scene(), Faults())
    execution = ExecutionAgentWrapper(sim)  # type: ignore[arg-type]
    novel = NovelPlanner(ScriptedProvider(table), execution.get_metadata,
                         constraints=Constraints.load(), skills=SkillLibrary(tmp_path / "s.db"))  # fmt: skip
    orch = Orchestrator(PlannerAgentWrapper(novel), execution, approval_gate=gate)  # type: ignore[arg-type]
    box = {}
    thread = threading.Thread(
        target=lambda: box.setdefault(
            "state",
            orch.run(SingleTask(goal="novel", estimated_goal="chill the apple")),
        )
    )
    thread.start()
    return orch, sim, thread, box


CHILL = plan("chill the apple", into("apple", "fridge", True) + [S("look_around")],
             [P("in_receptacle", "apple", "fridge")])  # fmt: skip


def test_a_worked_out_plan_is_previewed_and_can_be_edited(tmp_path):
    gate = ApprovalGate(timeout_s=10)
    orch, sim, thread, box = _novel_run(gate, tmp_path, {"chill the apple": CHILL})
    st = _wait_for_question(orch)
    q = st.pending_decision
    assert q["kind"] == "plan" and q["steps"][-1]["action"] == "look_around"
    assert all(
        s["status"] == "pending" for s in [{"status": "pending"}]
    )  # nothing ran yet
    apple = next(o for o in sim.objects if o["objectType"] == "Apple")
    assert apple["parentReceptacles"] == ["Table|1"]
    keep = [s for s in q["steps"] if s["action"] != "look_around"]  # leave one step out
    gate.decide(st.task_id, Decision("approve", keep))
    thread.join(5)
    state = box["state"]
    assert state.status.value == "succeeded"
    assert "look_around" not in [s.action for s in state.current_plan.steps]


def test_a_cancelled_preview_does_nothing(tmp_path):
    gate = ApprovalGate(timeout_s=10)
    orch, sim, thread, box = _novel_run(gate, tmp_path, {"chill the apple": CHILL})
    st = _wait_for_question(orch)
    gate.decide(st.task_id, Decision("cancel"))
    thread.join(5)
    assert box["state"].status.value == "failed" and not box["state"].execution_history
    apple = next(o for o in sim.objects if o["objectType"] == "Apple")
    assert apple["parentReceptacles"] == ["Table|1"]


# -- undo -----------------------------------------------------------------------------------------


def test_undo_restores_the_previous_state_in_the_simulator():
    sim = SyntheticSimulator(scene(), Faults())
    execution = ExecutionAgentWrapper(sim)  # type: ignore[arg-type]
    orch = Orchestrator(PlannerAgentWrapper(create_planner("rule_based")), execution)
    state = orch.run(SingleTask(goal="store", object="apple", target="fridge"))
    assert state.status.value == "succeeded"
    apple = next(o for o in sim.objects if o["objectType"] == "Apple")
    fridge = next(o for o in sim.objects if o["objectType"] == "Fridge")
    assert apple["parentReceptacles"] == ["Fridge|1"]

    steps, cannot, success = inverse_plan(state.undo_log)
    assert not cannot
    fixed = FixedPlanner()
    fixed.pending["undo:1"] = (steps, success)
    undo = Orchestrator(PlannerAgentWrapper(fixed), execution).run(  # type: ignore[arg-type]
        SingleTask(goal="undo", estimated_goal="undo:1")
    )
    assert undo.status.value == "succeeded"
    assert apple["parentReceptacles"] == ["Table|1"]
    assert fridge["isOpen"] is False
    assert all(v["ok"] for v in undo.verification)


def test_undo_of_toggles_and_irreversible_steps():
    log = [
        {"action": "open", "target": "Fridge|1", "before": {"isOpen": False}},
        {"action": "turn_on", "target": "Faucet|1", "before": {"isToggled": False}},
        {"action": "push", "target": "Egg|1", "before": {}},
        {"action": "close", "target": "Fridge|1", "before": {"isOpen": True}},
    ]
    steps, cannot, success = inverse_plan(log)
    assert cannot == ["push the egg"]
    assert [
        s["action"] for s in steps if s["action"] not in ("navigate", "locate")
    ] == ["open", "turn_off", "close"]
    assert {(p["kind"], p["object"]) for p in success} == {
        ("is_closed", "Fridge|1"),
        ("toggled_off", "Faucet|1"),
    }


# -- API -----------------------------------------------------------------------------------------


@pytest.fixture
def api(monkeypatch):
    from fastapi.testclient import TestClient

    from api.app import app
    from tests.test_api_phase3 import _wire

    def wire(objs):
        return _wire(SyntheticSimulator(objs, Faults()))

    with TestClient(app) as client:
        yield client, wire


def _wait(client, task_id, until=("succeeded", "failed", "cancelled")):
    for _ in range(400):
        body = client.get(f"/api/v1/tasks/{task_id}").json()
        if body["status"] in until:
            return body
        time.sleep(0.02)
    raise AssertionError("task did not finish")


def test_api_asks_which_cup_then_runs_the_chosen_one(api):
    client, wire = api
    sim = wire(two_cups())
    reply = client.post(
        "/api/v1/tasks", json={"instruction": "put the cup on the sofa"}
    )
    assert reply.status_code == 200 and reply.json()["kind"] == "clarify"
    choice = next(
        c for c in reply.json()["choices"] if c["label"] == "the cup on the table"
    )
    task = client.post(
        "/api/v1/tasks",
        json={"instruction": choice["instruction"], "object_id": choice["object_id"]},
    )
    assert task.status_code == 202
    assert _wait(client, task.json()["task_id"])["status"] == "succeeded"
    cups = {
        o["objectId"]: o["parentReceptacles"]
        for o in sim.objects
        if o["objectType"] == "Cup"
    }
    assert cups == {"Cup|1": ["Shelf|1"], "Cup|2": ["Sofa|1"]}


def test_api_no_the_other_one(api):
    client, wire = api
    sim = wire(two_cups())
    task = client.post(
        "/api/v1/tasks",
        json={"instruction": "put the cup on the sofa", "object_id": "Cup|1"},
    ).json()
    _wait(client, task["task_id"])
    fixed = client.post(f"/api/v1/tasks/{task['task_id']}/correct", json={})
    assert fixed.status_code == 202, fixed.text
    assert _wait(client, fixed.json()["task_id"])["status"] == "succeeded"
    cup2 = next(o for o in sim.objects if o["objectId"] == "Cup|2")
    assert cup2["parentReceptacles"] == ["Sofa|1"]


def test_api_risky_step_decision_and_undo(api):
    client, wire = api
    sim = wire(_dangerous_scene())
    task = client.post(
        "/api/v1/tasks", json={"instruction": "turn on the toaster"}
    ).json()
    for _ in range(200):
        body = client.get(f"/api/v1/tasks/{task['task_id']}").json()
        if body.get("pending_decision"):
            break
        time.sleep(0.02)
    assert body["pending_decision"]["kind"] == "step"
    assert (
        client.post(
            f"/api/v1/tasks/{task['task_id']}/decision", json={"choice": "approve"}
        ).status_code
        == 200
    )
    assert _wait(client, task["task_id"])["status"] == "succeeded"
    assert (
        client.post(
            f"/api/v1/tasks/{task['task_id']}/decision", json={"choice": "approve"}
        ).status_code
        == 409
    )

    preview = client.get(f"/api/v1/tasks/{task['task_id']}/undo").json()
    assert (
        preview["possible"]
        and [s["action"] for s in preview["steps"]][-1] == "turn_off"
    )
    undo = client.post(f"/api/v1/tasks/{task['task_id']}/undo")
    assert undo.status_code == 202
    uid = undo.json()["task_id"]
    # switching the toaster off is a step on a dangerous object too: MILO asks again
    for _ in range(200):
        body = client.get(f"/api/v1/tasks/{uid}").json()
        if body.get("pending_decision"):
            client.post(f"/api/v1/tasks/{uid}/decision", json={"choice": "approve"})
            break
        time.sleep(0.02)
    assert _wait(client, uid)["status"] == "succeeded"
    toaster = next(o for o in sim.objects if o["objectType"] == "Toaster")
    assert toaster["isToggled"] is False


def test_api_where_should_it_go_offers_places(api):
    client, wire = api
    wire(scene())
    reply = client.post(
        "/api/v1/tasks", json={"instruction": "put the mug away"}
    ).json()
    assert reply["kind"] == "clarify"
    assert any(
        c["instruction"] == "put the mug in the fridge" for c in reply["choices"]
    )

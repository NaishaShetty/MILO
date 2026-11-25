"""Roadmap 2, Phase 3: teach MILO a skill, save a mission as a skill, chain skills."""

from __future__ import annotations

import time

import pytest

from agents.execution_agent import ExecutionAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from learning.synthetic import Faults, SyntheticSimulator
from novel.eval_novel import scene
from novel.planner import NovelPlanner
from novel.providers import OfflineProvider
from novel.safety import Constraints
from novel.skills import MAX_DEPTH, SkillChainError, SkillLibrary
from novel.teach import TeachError, proposal_from_task, proposal_from_words
from orchestration.orchestrator import Orchestrator
from planner.factory import create_planner
from schemas.task import SingleTask


def _other_scene():
    """A different room: other distances, a table far away, no apple, a new vase."""
    objs = [o for o in scene() if o["objectType"] != "Apple"]
    for o in objs:
        o["distance"] = round(o["distance"] * 1.7, 2)
    objs.append({"objectId": "Vase|1", "objectType": "Vase", "distance": 3.1, "visible": True,
                 "pickupable": True, "parentReceptacles": ["Shelf|1"]})  # fmt: skip
    return objs


def _run_novel(command, skills, objects=None):
    sim = SyntheticSimulator(objects or scene(), Faults())
    execution = ExecutionAgentWrapper(sim)  # type: ignore[arg-type]
    novel = NovelPlanner(OfflineProvider(), execution.get_metadata,
                         constraints=Constraints.load(), skills=skills)  # fmt: skip
    state = Orchestrator(PlannerAgentWrapper(novel), execution).run(  # type: ignore[arg-type]
        SingleTask(goal="novel", estimated_goal=command)
    )
    return state, novel, sim


def _meta(objects=None):
    return SyntheticSimulator(objects or scene(), Faults()).get_metadata()


# -- teach mode -----------------------------------------------------------------------------


def test_steps_in_words_become_a_plan_with_pronouns_resolved():
    p = proposal_from_words(["pick up the mug", "put it on the table"], _meta())
    assert [s.action for s in p.steps][-1] == "place"
    assert p.steps[-1].target == "mug" and p.steps[-1].container == "table"
    assert {(q.kind, q.object) for q in p.success} >= {("in_receptacle", "mug")}


def test_steps_milo_cannot_understand_are_named():
    with pytest.raises(TeachError, match="step 2"):
        proposal_from_words(["pick up the mug", "juggle it"], _meta())
    with pytest.raises(TeachError):
        proposal_from_words(["   "], _meta())


def test_a_taught_skill_runs_back_then_is_reused_in_a_new_scene_with_other_objects(
    tmp_path,
):
    lib = SkillLibrary(tmp_path / "s.db")
    names = [o["objectType"].lower() for o in scene()]
    proposal = proposal_from_words(["pick up the mug", "put it on the table"], _meta())
    skill = lib.save("set something on the table", "set the mug on the table", proposal, names,
                     status="teaching")  # fmt: skip
    assert skill.template == "set the {o0} on the {o1}" and skill.status == "teaching"

    state, novel, _ = _run_novel("set the mug on the table", lib)  # the run-back
    assert state.status.value == "succeeded" and novel.log.source == "skill"
    assert lib.by_id(skill.skill_id).status == "candidate"

    # a different room, a different object, no language model at all
    state, novel, sim = _run_novel("set the vase on the table", lib, _other_scene())
    assert state.status.value == "succeeded"
    assert novel.log.source == "skill" and novel.log.model_calls == 0
    vase = next(o for o in sim.objects if o["objectType"] == "Vase")
    assert vase["parentReceptacles"] == ["Table|1"]


# -- save a mission as a skill -------------------------------------------------------------------


def test_a_successful_mission_can_be_saved_and_reused(tmp_path):
    sim = SyntheticSimulator(scene(), Faults())
    orch = Orchestrator(PlannerAgentWrapper(create_planner("rule_based")), ExecutionAgentWrapper(sim))  # type: ignore[arg-type]
    state = orch.run(SingleTask(goal="place", object="mug", target="shelf"))
    assert state.status.value == "succeeded"
    proposal, used = proposal_from_task(state)
    assert {"mug", "shelf"} <= set(used)
    lib = SkillLibrary(tmp_path / "s.db")
    skill = lib.save("shelve it", "pop the mug on the shelf", proposal, used)
    assert skill.template == "pop the {o0} on the {o1}"
    state, novel, _ = _run_novel("pop the bowl on the sofa", lib)
    assert state.status.value == "succeeded" and novel.log.source == "skill"


def test_only_successful_missions_can_be_saved():
    sim = SyntheticSimulator(
        scene(), Faults(kind="missing_object", target="mug", times=99)
    )
    orch = Orchestrator(PlannerAgentWrapper(create_planner("rule_based")), ExecutionAgentWrapper(sim))  # type: ignore[arg-type]
    state = orch.run(SingleTask(goal="place", object="mug", target="shelf"))
    assert state.status.value == "failed"
    with pytest.raises(TeachError, match="finished successfully"):
        proposal_from_task(state)


# -- chaining ----------------------------------------------------------------------------------


def _shelve_skill(lib):
    proposal = proposal_from_words(["put the book on the shelf"], _meta())
    return lib.save("shelve", "shelve the book", proposal, ["book", "shelf"])


def test_a_chained_skill_runs_end_to_end(tmp_path):
    lib = SkillLibrary(tmp_path / "s.db")
    _shelve_skill(lib)
    from novel.plan import NovelStep, Proposal

    chain = Proposal(
        goal="tidy two things",
        steps=[NovelStep("skill:shelve", "apple"), NovelStep("skill:shelve", "cup")],
    )
    lib.save("tidy two things", "tidy the apple and the cup", chain, ["apple", "cup"])
    state, novel, sim = _run_novel("tidy the tomato and the bowl", lib)
    assert state.status.value == "succeeded"
    for name in ("Tomato", "Bowl"):
        obj = next(o for o in sim.objects if o["objectType"] == name)
        assert obj["parentReceptacles"] == ["Shelf|1"]
    places = [s.action for s in state.current_plan.steps].count("place")
    assert places == 2


def test_skill_cycles_unknown_skills_and_depth_are_refused(tmp_path):
    lib = SkillLibrary(tmp_path / "s.db")
    from novel.plan import NovelStep, Proposal

    a = lib.save(
        "a", "alpha the mug", Proposal(steps=[NovelStep("look_around")]), ["mug"]
    )
    b = lib.save(
        "b", "beta the mug", Proposal(steps=[NovelStep("skill:a", "mug")]), ["mug"]
    )
    with pytest.raises(SkillChainError, match="loop"):
        lib.update_steps(a.skill_id, [{"action": "skill:b", "target": "{o0}"}])
    with pytest.raises(SkillChainError, match="don't know"):
        lib.save(
            "c",
            "gamma the mug",
            Proposal(steps=[NovelStep("skill:nope", "mug")]),
            ["mug"],
        )
    # a chain deeper than MAX_DEPTH
    prev = "b"
    for i in range(MAX_DEPTH + 1):
        name = f"d{i}"
        try:
            lib.save(
                name,
                f"delta{i} the mug",
                Proposal(steps=[NovelStep(f"skill:{prev}", "mug")]),
                ["mug"],
            )
        except SkillChainError as exc:
            assert "levels deep" in str(exc)
            break
        prev = name
    else:
        pytest.fail("depth limit never triggered")
    assert lib.by_id(b.skill_id) is not None


def test_rename_disable_and_delete(tmp_path):
    lib = SkillLibrary(tmp_path / "s.db")
    skill = _shelve_skill(lib)
    assert lib.rename(skill.skill_id, "put on shelf").name == "put on shelf"
    lib.set_status(skill.template, "disabled")
    assert lib.find("shelve the cup", ["cup", "shelf"]) is None
    assert lib.delete(skill.skill_id) and lib.by_id(skill.skill_id) is None
    d = _shelve_skill(lib).to_dict()
    assert d["success_rate"] == 1.0 and d["wording"] == "shelve the {o0}"


# -- API ----------------------------------------------------------------------------------------


@pytest.fixture
def api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import novel.factory as factory
    from api.app import app
    from tests.test_api_phase3 import _wire

    monkeypatch.setenv("MILO_SKILLS_DB", str(tmp_path / "api-skills.db"))
    monkeypatch.setenv("MILO_NOVEL_PROVIDER", "offline")
    factory._LIBRARIES.clear()
    _wire(SyntheticSimulator(scene(), Faults()))
    with TestClient(app) as client:
        yield client
    factory._LIBRARIES.clear()


def _wait(client, task_id):
    for _ in range(300):
        body = client.get(f"/api/v1/tasks/{task_id}").json()
        if body["status"] in ("succeeded", "failed", "cancelled"):
            return body
        time.sleep(0.02)
    raise AssertionError("task did not finish")


def test_api_teach_runs_back_then_the_skill_works_by_name_offline(api):
    body = api.post(
        "/api/v1/skills/teach",
        json={"name": "set the table", "wording": "set the mug on the table",
              "steps": ["pick up the mug", "put it on the table"]},  # fmt: skip
    )
    assert body.status_code == 202, body.text
    data = body.json()
    assert data["skill"]["status"] == "teaching"
    assert _wait(api, data["task"]["task_id"])["status"] == "succeeded"
    skills = api.get("/api/v1/skills").json()["skills"]
    assert skills[0]["status"] == "candidate" and skills[0]["success_rate"] == 1.0

    # an ordinary command with the taught wording runs the skill, no model configured
    task = api.post(
        "/api/v1/tasks", json={"instruction": "set the bowl on the table"}
    ).json()
    final = _wait(api, task["task_id"])
    assert final["status"] == "succeeded" and final["planner"] == "novel"
    assert final["current_plan"]["metadata"]["novel"]["source"] == "skill"


def test_api_teach_explains_problems(api):
    bad = api.post("/api/v1/skills/teach",
                   json={"name": "x", "wording": "do the thing", "steps": ["pick up the mug"]})  # fmt: skip
    assert (
        bad.status_code == 400
        and "Mention at least one object" in bad.json()["message"]
    )
    bad = api.post("/api/v1/skills/teach",
                   json={"name": "x", "wording": "wobble the mug", "steps": ["wobble the mug"]})  # fmt: skip
    assert bad.status_code == 400 and "step 1" in bad.json()["message"]


def test_api_save_edit_and_delete(api):
    task = api.post(
        "/api/v1/tasks", json={"instruction": "put the mug on the shelf"}
    ).json()
    assert _wait(api, task["task_id"])["status"] == "succeeded"
    saved = api.post(
        f"/api/v1/skills/from-task/{task['task_id']}", json={"name": "shelve it"}
    )
    assert saved.status_code == 200, saved.text
    sid = saved.json()["skill_id"]
    assert (
        api.patch(f"/api/v1/skills/{sid}", json={"name": "put it up high"}).json()[
            "name"
        ]
        == "put it up high"
    )
    assert (
        api.patch(f"/api/v1/skills/{sid}", json={"status": "disabled"}).json()["status"]
        == "disabled"
    )
    looped = api.patch(
        f"/api/v1/skills/{sid}",
        json={"steps": [{"action": "skill:put it up high", "target": "{o0}"}]},
    )
    assert looped.status_code == 400  # a skill can't call itself
    assert api.delete(f"/api/v1/skills/{sid}").status_code == 200
    assert api.delete(f"/api/v1/skills/{sid}").status_code == 404
    assert (
        api.post("/api/v1/skills/from-task/nope", json={"name": "x"}).status_code == 404
    )

"""Roadmap 2, Phase 2: novel task solving ("figure it out")."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agents.execution_agent import ExecutionAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from learning.synthetic import Faults, SyntheticSimulator
from novel.eval_novel import P, S, into, plan, scene
from novel.factory import make_probe
from novel.plan import PLAN_SCHEMA, ProposalError, parse_proposal
from novel.planner import NovelPlanner
from novel.providers import (
    ClaudeProvider,
    OfflineProvider,
    PlanRequest,
    ProviderError,
    ScriptedProvider,
    build_provider,
)
from novel.safety import Budgets, Constraints
from novel.skills import PROMOTE_AFTER, SkillLibrary, templatize
from novel.validate import check
from orchestration.orchestrator import Orchestrator
from schemas.task import SingleTask

CHILL = plan(
    "chill the apple",
    into("apple", "fridge", True),
    [P("in_receptacle", "apple", "fridge"), P("is_closed", "fridge")],
)


def _run(
    table_or_provider, tmp_path, command="chill the apple", sim=None, replans=3, **kw
):
    sim = sim or SyntheticSimulator(scene(), Faults())
    execution = ExecutionAgentWrapper(sim)  # type: ignore[arg-type]
    provider = (
        table_or_provider
        if hasattr(table_or_provider, "propose")
        else ScriptedProvider(table_or_provider)
    )
    holder = {}
    novel = NovelPlanner(
        provider,
        execution.get_metadata,
        constraints=kw.pop("constraints", Constraints.load()),
        skills=kw.pop("skills", SkillLibrary(tmp_path / "skills.db")),
        failure_source=lambda: [f.message for f in holder["o"]._current_state.failures],
        probe=make_probe(execution),
        **kw,
    )
    orch = Orchestrator(PlannerAgentWrapper(novel), execution)  # type: ignore[arg-type]
    holder["o"] = orch
    state = orch.run(
        SingleTask(goal="novel", estimated_goal=command), max_replans=replans
    )
    return state, novel, sim


# -- plan schema -------------------------------------------------------------------------


def test_proposals_are_parsed_strictly():
    p = parse_proposal(CHILL)
    assert p.is_plan and p.steps[0].action == "locate" and len(p.success) == 2
    assert parse_proposal({"question": "Which cup?"}).question == "Which cup?"
    for bad in (
        [],
        {},
        {"steps": [{"target": "x"}]},
        {"steps": [S("open", "x")], "success": [P("levitating", "x")]},
    ):
        with pytest.raises(ProposalError):
            parse_proposal(bad)
    assert PLAN_SCHEMA["additionalProperties"] is False


# -- validation --------------------------------------------------------------------------


def _meta():
    return SyntheticSimulator(scene(), Faults()).get_metadata()


def test_validation_inserts_missing_approach_steps_as_the_closest_feasible_plan():
    lazy = plan(
        "x",
        [S("open", "fridge"), S("pickup", "apple"), S("place", "apple", "fridge")],
        [],
    )
    result = check(parse_proposal(lazy), _meta(), Constraints.load())
    assert (
        result.ok and result.fixed is not None and "added the steps" in result.fix_note
    )
    actions = [s.action for s in result.fixed.steps]
    # everything is already in view, so only "go there" steps are added
    assert actions == ["navigate", "open", "navigate", "pickup", "navigate", "place"]
    assert result.fixed.steps[4].target == "fridge"  # back to the fridge before placing


def test_validation_skips_steps_that_are_already_done():
    meta = _meta()
    next(o for o in meta["objects"] if o["objectType"] == "Fridge")["isOpen"] = True
    result = check(parse_proposal(CHILL), meta, Constraints.load())
    assert result.ok and "skipped what was already done" in result.fix_note
    assert [s.action for s in result.fixed.steps].count("open") == 0


@pytest.mark.parametrize(
    "steps, needle",
    [
        ([S("throw", "apple")], "don't have an action called 'throw'"),
        ([S("act", "apple")], "don't have an action called 'act'"),
        (into("unicorn", "fridge", True), "can't see a unicorn"),
        (
            [
                S("locate", "apple"),
                S("navigate", "apple"),
                S("place", "apple", "fridge"),
            ],
            "holding target",
        ),
    ],
)
def test_validation_rejects_bad_plans_with_a_plain_reason(steps, needle):
    result = check(parse_proposal(plan("x", steps, [])), _meta(), Constraints.load())
    assert not result.ok and any(needle in p for p in result.problems)


def test_constraints_forbid_and_flag_risky_steps(tmp_path):
    c = Constraints.load()
    c.forbidden_objects = ["television"]
    assert "not allowed to touch" in c.forbidden("turn_on", "television")
    assert c.risk("push", "egg") and "fragile" in c.risk("push", "egg")
    assert c.risk("pickup", "knife") == "the knife could be dangerous"
    assert c.risk("navigate", "knife") is None
    result = check(
        parse_proposal(
            plan("x", [S("locate", "egg"), S("navigate", "egg"), S("push", "egg")], [])
        ),
        _meta(),
        Constraints.load(),
    )
    assert result.ok and result.risky[0]["action"] == "push"


# -- solving end to end ----------------------------------------------------------------------


def test_a_novel_command_is_planned_executed_and_verified(tmp_path):
    state, novel, sim = _run({"chill the apple": CHILL}, tmp_path)
    assert state.status.value == "succeeded"
    assert state.planner == "novel"
    assert state.thoughts[0]["text"] == "I don't know this one yet. Let me work it out."
    assert {v["kind"] for v in state.verification} == {"in_receptacle", "is_closed"}
    assert all(v["ok"] for v in state.verification)
    apple = next(o for o in sim.objects if o["objectType"] == "Apple")
    assert apple["parentReceptacles"] == ["Fridge|1"]


def test_the_second_attempt_reuses_the_saved_skill_without_a_model_call(tmp_path):
    skills = SkillLibrary(tmp_path / "s.db")
    table = {"chill the apple": CHILL}
    _, first, _ = _run(table, tmp_path, skills=skills)
    state, second, _ = _run({}, tmp_path, command="chill the tomato", skills=skills)
    assert first.log.model_calls == 1
    assert state.status.value == "succeeded"
    assert second.log.source == "skill" and second.log.model_calls == 0


def test_skill_is_promoted_after_repeated_success_on_different_objects(tmp_path):
    lib = SkillLibrary(tmp_path / "s.db")
    proposal = parse_proposal(CHILL)
    objs = ["apple", "fridge", "tomato"]
    for _ in range(PROMOTE_AFTER):
        skill = lib.record_success("chill the apple", objs, proposal)
    assert skill.status == "candidate"  # many wins, but only on one object
    tomato = parse_proposal(json.loads(json.dumps(CHILL).replace("apple", "tomato")))
    skill = lib.record_success("chill the tomato", objs, tomato)
    assert skill.status == "trusted" and skill.template == "chill the {o0}"
    assert skill.instantiate(["egg"]).steps[5].target == "egg"
    assert (
        lib.set_status(skill.template, "disabled")
        and lib.find("chill the egg", ["egg"]) is None
    )


def test_templates_are_order_stable_and_ignore_plurals():
    assert templatize("put the apples in the fridge", ["fridge", "apple"]) == (
        "put the {o0} in the {o1}",
        ["apple", "fridge"],
    )


def test_a_question_or_refusal_stops_without_acting(tmp_path):
    state, novel, _ = _run(
        {"chill it": {"question": "What should I chill?"}}, tmp_path, command="chill it"
    )
    assert state.status.value == "failed" and not state.execution_history
    assert "What should I chill?" in state.thoughts[-1]["text"]
    state, novel, _ = _run(
        {"fly": {"impossible": "I can't fly"}}, tmp_path, command="fly"
    )
    assert state.status.value == "failed" and novel.log.declined == "I can't fly"


def test_infeasible_plans_go_back_to_the_model_with_the_problems(tmp_path):
    bad = plan("x", [S("pickup", "unicorn")], [])
    state, novel, _ = _run({"chill the apple": [bad, CHILL]}, tmp_path)
    assert state.status.value == "succeeded"
    assert novel.log.model_calls == 2 and novel.log.caught_infeasible == 1
    assert any("can't see a unicorn" in f for f in novel.log.feedback)


def test_risky_steps_wait_for_the_users_ok(tmp_path):
    risky = plan("x", [S("locate", "egg"), S("navigate", "egg"), S("push", "egg")], [])
    state, novel, sim = _run(
        {"nudge the egg": risky}, tmp_path, command="nudge the egg"
    )
    assert state.status.value == "failed" and not state.execution_history
    assert "need your OK" in state.thoughts[-1]["text"]
    state, novel, _ = _run({"nudge the egg": risky}, tmp_path, command="nudge the egg",
                           confirm=lambda risky_steps: True)  # fmt: skip
    assert state.status.value == "succeeded"


def test_a_plan_whose_success_condition_is_false_is_replanned_with_the_reason(tmp_path):
    # first plan "succeeds" step by step but leaves the fridge open
    sloppy = plan("x", [s for s in into("apple", "fridge", True) if s["action"] != "close"],
                  [P("in_receptacle", "apple", "fridge"), P("is_closed", "fridge")])  # fmt: skip
    state, novel, _ = _run({"chill the apple": [sloppy, CHILL]}, tmp_path)
    assert state.status.value == "succeeded"
    assert novel.log.model_calls == 2
    assert any("fridge is open" in f for f in novel.log.feedback)


def test_exploration_probes_affordances_after_repeated_failure(tmp_path):
    # the fridge door is stuck shut until MILO has tried (and failed) twice
    # the way to the fridge stays blocked: retries and replans fail, so MILO probes
    blocked = Faults(kind="blocked_path", target="fridge", times=99)
    sim = SyntheticSimulator(scene(), blocked)
    state, novel, _ = _run({"chill the apple": CHILL}, tmp_path, sim=sim, replans=4)
    assert state.status.value == "failed"
    assert novel.log.attempts >= 3
    assert 1 <= novel.log.probes <= Constraints.load().budgets.max_probes
    assert any("tried to open the fridge" in o for o in novel.log.observations)
    # the failure is remembered as a lesson for next time
    assert novel.skills.lessons("chill the apple", novel.log.scene_objects)


# -- budgets and fallbacks ------------------------------------------------------------------------


def test_model_call_budget_stops_and_asks(tmp_path):
    bad = plan("x", [S("pickup", "unicorn")], [])
    c = Constraints.load()
    c.budgets = Budgets(max_model_calls=2)
    state, novel, _ = _run({"chill the apple": bad}, tmp_path, constraints=c)
    assert state.status.value == "failed" and novel.log.model_calls == 2
    assert not state.execution_history


def test_wall_time_budget(tmp_path):
    c = Constraints.load()
    c.budgets = Budgets(max_wall_s=-1)
    state, _, _ = _run({"chill the apple": CHILL}, tmp_path, constraints=c)
    assert (
        state.status.value == "failed"
        and "ran out of time" in state.thoughts[-1]["text"]
    )


def test_offline_provider_says_so(tmp_path, monkeypatch):
    state, _, _ = _run(OfflineProvider(), tmp_path)
    assert state.status.value == "failed" and "offline" in state.thoughts[-1]["text"]
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert isinstance(build_provider(), OfflineProvider)
    monkeypatch.setenv("MILO_NOVEL_PROVIDER", "offline")
    assert isinstance(build_provider(), OfflineProvider)


# -- the Claude provider with a stand-in client ------------------------------------------------------


class _Client:
    def __init__(self, response=None, error=None):
        self.calls = []
        self._response, self._error = response, error
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        if self._error:
            raise self._error
        return self._response


def _response(text, stop="end_turn"):
    return SimpleNamespace(
        stop_reason=stop, content=[SimpleNamespace(type="text", text=text)]
    )


REQ = PlanRequest(command="chill the apple", scene=[], holding=None, actions=[])


def test_claude_provider_sends_the_schema_and_caches():
    client = _Client(_response(json.dumps(CHILL)))
    provider = ClaudeProvider(client=client)
    assert provider.propose(REQ) == CHILL and provider.propose(REQ) == CHILL
    assert len(client.calls) == 1  # second answer came from the cache
    sent = client.calls[0]
    assert sent["model"] == "claude-opus-5-5"
    assert sent["output_config"]["format"] == {
        "type": "json_schema",
        "schema": PLAN_SCHEMA,
    }
    assert sent["fallbacks"] == "default"


@pytest.mark.parametrize(
    "response, needle",
    [
        (_response("", stop="refusal"), "declined"),
        (_response("{not json"), "valid JSON"),
        (_response("{}", stop="max_tokens"), "cut off"),
    ],
)
def test_claude_provider_failures_become_plain_reasons(response, needle):
    with pytest.raises(ProviderError, match=needle):
        ClaudeProvider(client=_Client(response)).propose(REQ)


def test_claude_provider_timeout_is_a_plain_reason():
    import anthropic
    import httpx

    error = anthropic.APITimeoutError(request=httpx.Request("POST", "https://x"))
    with pytest.raises(ProviderError, match="took too long"):
        ClaudeProvider(client=_Client(error=error)).propose(REQ)


# -- API routing ----------------------------------------------------------------------------------------


def test_api_routes_unknown_commands_to_the_novel_planner(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    import novel.factory as factory
    import novel.providers as providers
    from api.app import app
    from api.routes.tasks import get_language_agent

    monkeypatch.setenv("MILO_SKILLS_DB", str(tmp_path / "s.db"))
    scripted = ScriptedProvider({"chill the apple": CHILL})
    monkeypatch.setattr(providers, "build_provider", lambda: scripted)
    monkeypatch.setattr(factory, "build_provider", lambda: scripted)
    from tests.test_api_phase3 import _wire  # the API tests' simulator wiring

    _wire(SyntheticSimulator(scene(), Faults()))
    agent = MagicMock()
    agent.parse.return_value = None
    app.dependency_overrides[get_language_agent] = lambda: agent
    try:
        client = TestClient(app)
        body = client.post(
            "/api/v1/tasks", json={"instruction": "chill the apple"}
        ).json()
        assert body["understood_as"] == "I don't know this yet, let me work it out"
        import time

        for _ in range(200):
            final = client.get(f"/api/v1/tasks/{body['task_id']}").json()
            if final["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.02)
        assert final["status"] == "succeeded" and final["planner"] == "novel"
    finally:
        app.dependency_overrides.pop(get_language_agent, None)

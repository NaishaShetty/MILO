"""The harder benchmark tiers: out-of-view objects, multi-goal missions, competing routes."""

from __future__ import annotations

from benchmark.run import case_scene, run_case
from benchmark.suite import (
    hard_cases,
    long_cases,
    memory_cases,
    memory_synonym_cases,
    route_cases,
)
from learning.synthetic import Faults, SyntheticSimulator
from verification.predicates import Predicate, final_state_predicates


def test_hidden_object_is_found_only_at_its_real_place():
    sim = SyntheticSimulator(
        [
            {"objectId": "Shelf|1", "objectType": "Shelf", "distance": 3.0},
            {"objectId": "Mug|1", "objectType": "Mug", "distance": 2.0, "hidden": True,
             "pickupable": True, "parentReceptacles": ["Shelf|1"]},
        ]  # fmt: skip
    )
    mug = sim._obj("Mug|1")
    assert mug["visible"] is False
    assert not sim.navigate_to("Mug|1").metadata["lastActionSuccess"]
    sim.look_around()
    assert mug["visible"] is False  # looking around doesn't reveal it
    assert sim.navigate_to("Shelf|1").metadata["lastActionSuccess"]
    assert (
        mug["visible"] is True
        and sim.navigate_to("Mug|1").metadata["lastActionSuccess"]
    )


def test_fault_target_can_name_one_object_of_a_type():
    objects = [
        {"objectId": f"Shelf|{i}", "objectType": "Shelf", "distance": 2.0 * i}
        for i in (1, 2)
    ]
    sim = SyntheticSimulator(
        objects, Faults(kind="blocked_path", target="Shelf|1", times=99)
    )
    assert not sim.navigate_to("Shelf|1").metadata["lastActionSuccess"]
    assert sim.navigate_to("Shelf|2").metadata["lastActionSuccess"]


def test_route_cases_add_a_second_farther_receptacle():
    case = route_cases()[0]
    shelves = [o for o in case_scene(case) if o["objectType"] == "Shelf"]
    assert [o["objectId"] for o in shelves] == ["Shelf|1", "Shelf|2"]
    assert case.fault_target == "Shelf|1" and case.fault_times == 99


def test_later_goals_supersede_earlier_ones_on_the_same_slot():
    store = [Predicate("in_receptacle", "apple", "fridge"), Predicate("hand_empty")]
    fetch = [Predicate("held", "mug")]
    final = final_state_predicates([store, fetch])
    assert Predicate("hand_empty") not in final
    assert (
        Predicate("held", "mug") in final
        and Predicate("in_receptacle", "apple", "fridge") in final
    )
    opened_then_closed = final_state_predicates(
        [[Predicate("is_open", "cabinet")], [Predicate("is_closed", "cabinet")]]
    )
    assert opened_then_closed == [Predicate("is_closed", "cabinet")]


def test_memory_separates_planners_on_out_of_view_objects():
    case = memory_cases()[0]  # fetch the mug, which starts out of view
    assert run_case(case, "rule_based")["success"]  # uses "where it usually is"
    assert not run_case(case, "rule_based", memory=False)["success"]
    assert not run_case(case, "htn")["success"]  # HTN plans without memory hints


def test_multi_goal_mission_ending_with_a_fetch_succeeds():
    case = next(c for c in long_cases() if c.case_id.startswith("long-store-apple"))
    assert run_case(case, "rule_based")["success"]


def test_tier_sizes():
    assert (len(memory_cases()), len(long_cases()), len(route_cases())) == (8, 6, 4)
    assert len(memory_synonym_cases()) == 8
    assert len(hard_cases()) == 32


def test_react_without_a_model_is_reported_as_not_measured():
    from benchmark.run import markdown, run

    report = run("ci", planners=["react", "rule_based"], ablations=False)
    assert report["planners"]["react"] == {
        "not_measured": "needs a model (--react-model)"
    }
    assert report["react_model"] is None
    assert "react | not measured" in markdown(report)


def test_react_whose_model_never_answers_is_not_reported_as_measured(monkeypatch):
    import benchmark.run as br
    from language.exceptions import LLMProviderError

    class Broken:
        def complete(self, request):
            raise LLMProviderError("no model here")  # what the real client raises

    monkeypatch.setattr(
        br, "_local_react_client", lambda model: br.CountingClient(Broken())
    )
    report = br.run("ci", planners=["react"], ablations=False, react_model="qwen2.5:7b")
    assert "not_measured" in report["planners"]["react"]
    assert "never answered" in report["planners"]["react"]["not_measured"]


def test_react_plans_handed_to_rule_based_are_counted(monkeypatch):
    import benchmark.run as br
    from language.llm_client import LLMResponse

    class Nonsense:
        """Always answers, never with a usable plan, so ReAct falls back every time."""

        def complete(self, request):
            return LLMResponse(content="no idea", provider="test", model="m",
                               latency_ms=1.0)  # fmt: skip

    monkeypatch.setattr(
        br, "_local_react_client", lambda model: br.CountingClient(Nonsense())
    )
    report = br.run("ci", planners=["react"], ablations=False, react_model="m")
    fb = report["react_fallback"]
    assert fb["cases_with_fallback"] >= fb["cases"] - 1 > 0  # one case never plans
    assert fb["success_without_fallback"] < 2 / fb["cases"]  # only that one case
    assert "handed at least one plan" in br.markdown(report)


def test_impossible_requests_are_refused_before_acting():
    from benchmark.suite import impossible_cases

    for planner in ("rule_based", "behavior_tree", "htn"):
        rows = [run_case(c, planner) for c in impossible_cases()]
        assert not any(r["mission_succeeded"] for r in rows), planner
        refused = [r["case"] for r in rows if r["success"]]
        # the unicorn isn't in the scene, so nothing says it can't be fetched
        assert set(refused) == {c.case_id for c in impossible_cases()} - {
            "impossible-fetch-unicorn"
        }, planner


def test_the_simulator_refuses_what_ai2thor_refuses():
    from benchmark.suite import Case

    sim = SyntheticSimulator(case_scene(Case("x", "known", "find", "apple")))
    sim.navigate_to("Fridge|1")
    assert not sim.pickup_object("Fridge|1").metadata["lastActionSuccess"]
    sim.navigate_to("Apple|1")
    assert not sim.open_object("Apple|1").metadata["lastActionSuccess"]
    assert sim.pickup_object("Apple|1").metadata["lastActionSuccess"]

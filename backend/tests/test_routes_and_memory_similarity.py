"""Competing routes (switch to another instance, remember the blocked one) and finding a
remembered place stored under another name (similarity fallback)."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from typing import List

from agents.execution_agent import ExecutionAgentWrapper
from agents.memory_agent import MemoryAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from benchmark.run import _memory, case_scene, run_case
from benchmark.suite import SYNONYMS, memory_synonym_cases, route_cases
from learning.synthetic import Faults, SyntheticSimulator
from orchestration.orchestrator import Orchestrator
from planner.factory import create_planner
from planner.rule_based import _similar_location_hint
from schemas.task import SingleTask
from verification.predicates import Predicate


def test_every_planner_reaches_the_other_shelf_when_the_near_one_is_blocked():
    for planner in ("rule_based", "behavior_tree", "htn"):
        for case in route_cases():
            assert run_case(case, planner)["success"], (planner, case.case_id)
            assert not run_case(case, planner, recovery=False)["success"]


def test_the_blocked_instance_is_remembered_and_avoided_before_acting(monkeypatch):
    monkeypatch.setenv("MILO_GOAL_CHECK", "enforce")
    case = route_cases()[0]
    objects = case_scene(case)
    failed: List[int] = []
    with tempfile.TemporaryDirectory() as tmp:
        memory = _memory(tmp, objects)
        for obj in ("mug", "bowl"):
            sim = SyntheticSimulator([dict(o) for o in objects],
                                     Faults(kind="blocked_path", target="Shelf|1", times=99))  # fmt: skip
            orch = Orchestrator(PlannerAgentWrapper(create_planner("rule_based")),
                                ExecutionAgentWrapper(sim), memory_agent=MemoryAgentWrapper(memory))  # fmt: skip
            state = orch.run(SingleTask(goal="place", object=obj, target="shelf"))
            assert state.status.value == "succeeded"
            failed.append(sum(s.status.value == "failed" for r in state.execution_history
                              for s in r.step_results))  # fmt: skip
    assert failed[0] > 0  # the first mission found out the hard way
    assert failed[1] == 0  # the second planned around it before acting


def test_on_the_shelf_means_any_shelf_unless_one_is_named():
    meta = {"objects": [
        {"objectId": "Shelf|1", "objectType": "Shelf", "distance": 1.0},
        {"objectId": "Shelf|2", "objectType": "Shelf", "distance": 6.0},
        {"objectId": "Mug|1", "objectType": "Mug", "parentReceptacles": ["Shelf|2"]},
    ]}  # fmt: skip
    assert Predicate("in_receptacle", "mug", "shelf").check(meta).ok
    assert Predicate("in_receptacle", "mug", "Shelf|2").check(meta).ok
    assert not Predicate("in_receptacle", "mug", "Shelf|1").check(meta).ok


@dataclass
class _R:
    similarity: float = 0.9  # query similarity: deliberately not what decides


def test_similarity_fallback_compares_names_not_the_query(monkeypatch):
    monkeypatch.setenv("MEMORY_EMBEDDING_PROVIDER", "hashing")
    hint = _similar_location_hint(
        [("shelf", _R(), "ceramic mug"), ("table", _R(), "apple")], "mug"
    )
    assert hint is not None and hint[0] == "shelf"
    # Another thing entirely, however relevant to the query: no hint.
    assert _similar_location_hint([("kitchen", _R(), "refrigerator")], "mug") is None
    # Two equally good names: no clear winner, no hint.
    assert (
        _similar_location_hint(
            [("shelf", _R(), "red mug"), ("table", _R(), "blue mug")], "mug"
        )
        is None
    )
    assert _similar_location_hint([], "mug") is None


def test_synonym_tier_uses_held_out_paraphrases():
    probe = {"coffee mug", "paperback novel", "water bottle", "dinner plate", "teacup",
             "cherry tomato", "spud", "hen's egg"}  # fmt: skip
    assert not probe & set(SYNONYMS.values())
    case = memory_synonym_cases()[0]
    assert case.aliases == (("mug", "ceramic mug"),) and case.hidden == ("mug",)

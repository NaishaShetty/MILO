"""
test_planner_memory_context.py

Purpose
-------
Unit tests proving `RuleBasedPlanner` actually consumes a
`memory.agent.PlannerMemoryContext` -- Phase 6.3 spec section 16's
"causal verification": memory ON vs. memory OFF must produce
measurably different planner input/plans under controlled conditions.
Also covers section 8 ("current observations can override stale
memory") and section 6/7 ("memory as structured input, never hidden
state, never dictating the final plan").
"""

from __future__ import annotations

from memory.agent import PlannerMemoryContext
from memory.models import MemoryProvenance
from memory.retrieval import MemoryResult
from memory.semantics import build_semantic_memory
from planner.factory import create_planner
from planner.rule_based import RuleBasedPlanner
from planner.state import WorldState
from schemas.task import SingleTask


def _location_result(subject, predicate, obj, *, confidence=0.9, memory_id=None):
    kwargs = dict(provenance=MemoryProvenance.OBSERVATION, confidence=confidence)
    if memory_id is not None:
        kwargs["memory_id"] = memory_id
    memory = build_semantic_memory(subject, predicate, obj, **kwargs)
    return MemoryResult(
        memory=memory,
        similarity=0.8,
        final_score=0.85,
        ranking_components={},
        retrieval_metadata={},
    )


class TestMemoryOnOffCausalDifference:
    def test_find_goal_without_memory_only_locates_the_object(self):
        task = SingleTask(goal="find", object="mug")
        result = RuleBasedPlanner().plan(task, WorldState())
        steps = [(s.action, s.target) for s in result.plan.steps]
        assert steps == [("locate", "mug"), ("navigate", "mug")]

    def test_find_goal_with_memory_visits_hinted_location_first(self):
        task = SingleTask(goal="find", object="mug")
        memory_context = PlannerMemoryContext(
            query="find mug",
            results=[_location_result("mug", "located_on", "table")],
        )
        result = RuleBasedPlanner().plan(task, WorldState(), memory_context)
        steps = [(s.action, s.target) for s in result.plan.steps]
        assert steps == [
            ("locate", "table"),
            ("navigate", "table"),
            ("locate", "mug"),
            ("navigate", "mug"),
        ]

    def test_memory_on_and_off_plans_differ_for_the_identical_task(self):
        task = SingleTask(goal="find", object="mug")
        memory_context = PlannerMemoryContext(
            query="find mug",
            results=[_location_result("mug", "located_on", "table")],
        )
        without_memory = RuleBasedPlanner().plan(task, WorldState())
        with_memory = RuleBasedPlanner().plan(task, WorldState(), memory_context)

        without_targets = [s.target for s in without_memory.plan.steps]
        with_targets = [s.target for s in with_memory.plan.steps]
        assert without_targets != with_targets
        assert "table" in with_targets
        assert "table" not in without_targets
        assert len(with_memory.plan.steps) > len(without_memory.plan.steps)

    def test_both_plans_remain_valid(self):
        task = SingleTask(goal="find", object="mug")
        memory_context = PlannerMemoryContext(
            query="find mug",
            results=[_location_result("mug", "located_on", "table")],
        )
        without_memory = RuleBasedPlanner().plan(task, WorldState())
        with_memory = RuleBasedPlanner().plan(task, WorldState(), memory_context)
        assert without_memory.success is True
        assert with_memory.success is True


class TestMemoryDoesNotDictatePlan:
    def test_memory_hint_is_additive_not_a_replacement(self):
        """The plan still ends with locate/navigate on the object itself --
        memory only reorders search, it never substitutes the final action."""
        task = SingleTask(goal="find", object="mug")
        memory_context = PlannerMemoryContext(
            query="find mug",
            results=[_location_result("mug", "located_on", "table")],
        )
        result = RuleBasedPlanner().plan(task, WorldState(), memory_context)
        last_two = [(s.action, s.target) for s in result.plan.steps[-2:]]
        assert last_two == [("locate", "mug"), ("navigate", "mug")]

    def test_low_confidence_memory_is_ignored(self):
        task = SingleTask(goal="find", object="mug")
        memory_context = PlannerMemoryContext(
            query="find mug",
            results=[_location_result("mug", "located_on", "table", confidence=0.1)],
        )
        result = RuleBasedPlanner().plan(task, WorldState(), memory_context)
        steps = [(s.action, s.target) for s in result.plan.steps]
        assert steps == [("locate", "mug"), ("navigate", "mug")]

    def test_irrelevant_memory_does_not_affect_plan(self):
        task = SingleTask(goal="find", object="mug")
        memory_context = PlannerMemoryContext(
            query="find mug",
            results=[_location_result("refrigerator", "located_in", "kitchen")],
        )
        result = RuleBasedPlanner().plan(task, WorldState(), memory_context)
        steps = [(s.action, s.target) for s in result.plan.steps]
        assert steps == [("locate", "mug"), ("navigate", "mug")]

    def test_explicit_task_destination_is_never_overridden_by_memory(self):
        """A deposit target the user explicitly named (task.target) must
        never be replaced by a memory-suggested location."""
        task = SingleTask(goal="place", object="mug", target="counter")
        memory_context = PlannerMemoryContext(
            query="place mug",
            results=[_location_result("mug", "located_on", "table")],
        )
        result = RuleBasedPlanner().plan(task, WorldState(), memory_context)
        place_step = next(s for s in result.plan.steps if s.action == "place")
        assert place_step.parameters["container"] == "counter"


class TestCurrentPerceptionOverridesStaleMemory:
    def test_already_located_object_skips_memory_hint(self):
        task = SingleTask(goal="find", object="mug")
        memory_context = PlannerMemoryContext(
            query="find mug",
            results=[_location_result("mug", "located_on", "table")],
        )
        state = WorldState()
        state.object("mug").is_located = True  # current perception already knows
        result = RuleBasedPlanner().plan(task, state, memory_context)
        steps = [(s.action, s.target) for s in result.plan.steps]
        assert steps == [("locate", "mug"), ("navigate", "mug")]


class TestPlanMetadataExplainability:
    def test_plan_metadata_records_memory_query_and_ids(self):
        task = SingleTask(goal="find", object="mug")
        result_memory = _location_result(
            "mug", "located_on", "table", memory_id="mem-1"
        )
        memory_context = PlannerMemoryContext(
            query="find mug", results=[result_memory], episode_id="ep-1"
        )
        result = RuleBasedPlanner().plan(task, WorldState(), memory_context)
        summary = result.plan.metadata["memory_context"]
        assert summary["query"] == "find mug"
        assert summary["memory_ids"] == ["mem-1"]
        assert summary["count"] == 1

    def test_no_memory_context_key_when_memory_not_used(self):
        task = SingleTask(goal="find", object="mug")
        result = RuleBasedPlanner().plan(task, WorldState())
        assert "memory_context" not in result.plan.metadata

    def test_hinted_steps_are_tagged_with_memory_source(self):
        task = SingleTask(goal="find", object="mug")
        memory_context = PlannerMemoryContext(
            query="find mug",
            results=[
                _location_result("mug", "located_on", "table", memory_id="mem-42")
            ],
        )
        result = RuleBasedPlanner().plan(task, WorldState(), memory_context)
        hinted = result.plan.steps[0]
        assert hinted.parameters["source"] == "memory"
        assert hinted.parameters["memory_id"] == "mem-42"


class TestOtherStrategiesAcceptMemoryContextForInterfaceConsistency:
    def test_behavior_tree_planner_accepts_memory_context_without_error(self):
        task = SingleTask(goal="find", object="mug")
        memory_context = PlannerMemoryContext(
            query="find mug",
            results=[_location_result("mug", "located_on", "table")],
        )
        planner = create_planner("behavior_tree")
        result = planner.plan(task, WorldState(), memory_context)
        assert result.success is True

    def test_react_planner_without_llm_client_falls_back_and_still_uses_memory(self):
        task = SingleTask(goal="find", object="mug")
        memory_context = PlannerMemoryContext(
            query="find mug",
            results=[_location_result("mug", "located_on", "table")],
        )
        planner = create_planner("react", llm_client=None, fallback_to_rule_based=True)
        result = planner.plan(task, WorldState(), memory_context)
        assert result.success is True
        steps = [(s.action, s.target) for s in result.plan.steps]
        assert ("locate", "table") in steps

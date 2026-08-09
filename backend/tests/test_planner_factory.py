"""
test_planner_factory.py

Purpose
-------
Unit tests for `planner/factory.py`: planner selection via
`create_planner()`, and that every strategy produced by the factory
returns a `PlanningResult` with a consistent output schema regardless
of which concrete `Planner` subclass built it.

How to run
-----------
    cd backend
    python -m pytest tests/test_planner_factory.py -v
"""

import pytest

from planner.behavior_tree import BehaviorTreePlanner
from planner.factory import PlannerType, available_planner_types, create_planner
from planner.react import ReActPlanner
from planner.rule_based import RuleBasedPlanner
from planner.state import WorldState
from schemas.task import SingleTask

TASK = SingleTask(goal="pick_up", object="mug")


def test_available_planner_types_lists_all_three():
    assert set(available_planner_types()) == {"rule_based", "react", "behavior_tree"}


@pytest.mark.parametrize(
    "planner_type,expected_class",
    [
        (PlannerType.RULE_BASED, RuleBasedPlanner),
        (PlannerType.BEHAVIOR_TREE, BehaviorTreePlanner),
        (PlannerType.REACT, ReActPlanner),
    ],
)
def test_factory_builds_the_requested_strategy(planner_type, expected_class):
    planner = create_planner(planner_type)
    assert isinstance(planner, expected_class)


def test_factory_accepts_string_planner_type():
    planner = create_planner("rule_based")
    assert isinstance(planner, RuleBasedPlanner)


def test_factory_rejects_unknown_planner_type():
    with pytest.raises(ValueError):
        create_planner("not_a_real_planner")


def test_every_strategy_produces_consistent_output_schema():
    for planner_type in PlannerType:
        planner = create_planner(planner_type)
        result = planner.plan(TASK, WorldState.initial())
        assert result.planner_type == planner_type.value
        assert result.success is True
        assert result.plan is not None
        assert result.validation is not None
        assert result.latency_ms >= 0

"""
test_planner_behavior_tree.py

Purpose
-------
Unit tests for `planner/behavior_tree.py`: the `Sequence`/`Selector`/
`Condition`/`Action`/`Retry` node types individually, failure
propagation through a `Sequence`, and `BehaviorTreePlanner`'s full
integration with the `Planner` interface.

How to run
-----------
    cd backend
    python -m pytest tests/test_planner_behavior_tree.py -v
"""

from planner.behavior_tree import (
    Action,
    BehaviorTreePlanner,
    Condition,
    NodeStatus,
    Retry,
    Selector,
    Sequence,
    TickContext,
)
from planner.state import WorldState
from schemas.task import SingleTask


def test_sequence_succeeds_only_if_every_child_succeeds():
    ctx = TickContext(state=WorldState.initial())
    always_true = Condition("t", lambda s: True)
    always_false = Condition("f", lambda s: False)

    assert Sequence("s", [always_true, always_true]).tick(ctx) == NodeStatus.SUCCESS
    assert Sequence("s", [always_true, always_false]).tick(ctx) == NodeStatus.FAILURE


def test_sequence_failure_propagation_stops_remaining_children():
    ctx = TickContext(state=WorldState.initial())
    calls = []

    def recording_condition(name, result):
        def _predicate(state):
            calls.append(name)
            return result

        return Condition(name, _predicate)

    seq = Sequence(
        "s",
        [
            recording_condition("a", True),
            recording_condition("b", False),
            recording_condition("c", True),
        ],
    )
    assert seq.tick(ctx) == NodeStatus.FAILURE
    assert calls == ["a", "b"]  # "c" never ticked


def test_selector_returns_first_non_failure():
    ctx = TickContext(state=WorldState.initial())
    fail = Condition("f", lambda s: False)
    succeed = Condition("s", lambda s: True)
    assert Selector("sel", [fail, succeed]).tick(ctx) == NodeStatus.SUCCESS
    assert Selector("sel", [fail, fail]).tick(ctx) == NodeStatus.FAILURE


def test_condition_reads_world_state():
    state = WorldState.initial()
    state.object("apple").is_located = True
    ctx = TickContext(state=state)
    cond = Condition("located", lambda s: s.object("apple").is_located)
    assert cond.tick(ctx) == NodeStatus.SUCCESS


def test_action_appends_plan_step_only_on_success():
    state = WorldState.initial()
    ctx = TickContext(state=state)
    # locate has no preconditions -> always succeeds
    assert Action("locate", "apple").tick(ctx) == NodeStatus.SUCCESS
    assert len(ctx.steps) == 1
    assert ctx.steps[0].action == "locate"

    # navigate requires locate first; apple is not located in a *fresh* state
    fresh_ctx = TickContext(state=WorldState.initial())
    assert Action("navigate", "apple").tick(fresh_ctx) == NodeStatus.FAILURE
    assert fresh_ctx.steps == []


def test_retry_reties_up_to_max_attempts():
    ctx = TickContext(state=WorldState.initial())
    attempts = {"count": 0}

    def flaky(state):
        attempts["count"] += 1
        return attempts["count"] >= 2

    node = Retry("retry", Condition("flaky", flaky), max_attempts=3)
    assert node.tick(ctx) == NodeStatus.SUCCESS
    assert attempts["count"] == 2


def test_behavior_tree_planner_matches_rule_based_step_sequence():
    task = SingleTask(goal="store", object="apple", target="refrigerator")
    result = BehaviorTreePlanner().plan(task, WorldState.initial())
    assert result.success
    actions = [(s.action, s.target) for s in result.plan.steps]
    assert actions == [
        ("locate", "apple"),
        ("navigate", "apple"),
        ("pickup", "apple"),
        ("locate", "refrigerator"),
        ("navigate", "refrigerator"),
        ("open", "refrigerator"),
        ("place", "apple"),
        ("close", "refrigerator"),
    ]
    assert "behavior_tree" in result.plan.metadata


def test_behavior_tree_planner_exposes_tree_for_visualization():
    task = SingleTask(goal="pick_up", object="mug")
    result = BehaviorTreePlanner().plan(task, WorldState.initial())
    tree = result.plan.metadata["behavior_tree"]
    assert tree["type"] == "Sequence"
    assert len(tree["children"]) == 3

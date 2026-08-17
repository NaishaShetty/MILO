"""
test_planner_rule_based.py

Purpose
-------
Unit tests for `planner/rule_based.py`'s `RuleBasedPlanner` -- the
deterministic baseline. Covers section 14's "Rule-based planner"
bullets: store, pickup, move/deliver, open/close, and an invalid task
(missing required field for its goal).

How to run
-----------
    cd backend
    python -m pytest tests/test_planner_rule_based.py -v
"""

from planner.rule_based import RuleBasedPlanner
from planner.state import WorldState
from schemas.task import SingleTask

PLANNER = RuleBasedPlanner()


def _plan(**task_kwargs):
    task = SingleTask(**task_kwargs)
    return PLANNER.plan(task, WorldState.initial())


def test_store_produces_expected_eight_step_sequence():
    result = _plan(goal="store", object="apple", target="refrigerator")
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
    assert result.validation.valid
    assert result.validation.goal_satisfied is True


def test_pick_up_produces_three_step_sequence():
    result = _plan(goal="pick_up", object="mug")
    assert result.success
    assert [s.action for s in result.plan.steps] == ["locate", "navigate", "pickup"]


def test_deliver_navigates_to_destination_after_pickup():
    result = _plan(goal="deliver", object="package", target="office")
    assert result.success
    assert [s.action for s in result.plan.steps] == [
        "locate",
        "navigate",
        "pickup",
        "locate",
        "navigate",
    ]
    assert result.plan.steps[-1].target == "office"


def test_open_and_close_goals():
    open_result = _plan(goal="open", object="drawer")
    assert [s.action for s in open_result.plan.steps] == ["locate", "navigate", "open"]

    close_result = _plan(goal="close", object="drawer")
    assert [s.action for s in close_result.plan.steps] == [
        "locate",
        "navigate",
        "close",
    ]


def test_place_goal_has_no_open_close_for_non_container_target():
    result = _plan(goal="place", object="book", target="table")
    assert result.success
    assert "open" not in [s.action for s in result.plan.steps]
    assert "close" not in [s.action for s in result.plan.steps]


def test_place_goal_inserts_open_close_for_a_known_closed_container():
    # Regression test: "place" (unlike "store") never inserted an
    # `open` step, so placing into a receptacle `state` already knows
    # is closed used to fail the `place` precondition outright.
    state = WorldState.initial()
    state.object("drawer").is_open = False
    task = SingleTask(goal="place", object="apple", target="drawer")
    result = PLANNER.plan(task, state)
    assert result.success
    assert [s.action for s in result.plan.steps] == [
        "locate",
        "navigate",
        "pickup",
        "locate",
        "navigate",
        "open",
        "place",
        "close",
    ]


def test_place_goal_does_not_reopen_an_already_open_container():
    state = WorldState.initial()
    state.object("drawer").is_open = True
    task = SingleTask(goal="place", object="apple", target="drawer")
    result = PLANNER.plan(task, state)
    assert result.success
    assert "open" not in [s.action for s in result.plan.steps]
    assert "close" not in [s.action for s in result.plan.steps]


def test_store_goal_does_not_reopen_an_already_open_container():
    # "store" used to unconditionally add `open`, which would itself
    # fail its own `not_open` precondition against a container already
    # known to be open.
    state = WorldState.initial()
    state.object("refrigerator").is_open = True
    task = SingleTask(goal="store", object="apple", target="refrigerator")
    result = PLANNER.plan(task, state)
    assert result.success
    assert "open" not in [s.action for s in result.plan.steps]
    assert "close" not in [s.action for s in result.plan.steps]


def test_generic_fallback_goal_still_produces_a_plan():
    result = _plan(goal="turn_on", object="lamp")
    assert result.success
    assert result.plan.steps[-1].action == "act"


def test_invalid_task_missing_object_for_store_goal():
    task = SingleTask(goal="store", target="refrigerator")  # no object
    result = PLANNER.plan(task, WorldState.initial())
    assert not result.success
    assert result.plan is None
    assert "object" in result.errors[0]


def test_invalid_task_no_goal_at_all():
    task = SingleTask()
    result = PLANNER.plan(task, WorldState.initial())
    assert not result.success


def test_deterministic_repeated_planning_is_identical():
    first = _plan(goal="store", object="apple", target="refrigerator")
    second = _plan(goal="store", object="apple", target="refrigerator")
    assert [s.action for s in first.plan.steps] == [s.action for s in second.plan.steps]
    assert [s.target for s in first.plan.steps] == [s.target for s in second.plan.steps]

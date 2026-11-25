"""
test_task_library.py

Every kind of job the task library advertises must actually be plannable
by *every* planner (or fall back cleanly with a plain-language reason),
and the new primitives (turn on/off, fetch-to-me) must validate and
resume correctly. Simulator-free -- planner level only; the end-to-end
runs are in `test_task_scenarios.py`.
"""

from __future__ import annotations

import pytest

from planner.factory import create_planner
from planner.state import WorldState
from planner.task_library import (
    COMPOSITE_GOALS,
    TASK_LIBRARY,
    capabilities_sentence,
    library_as_dicts,
)
from schemas.task import SingleTask

PLANNERS = ["rule_based", "htn", "behavior_tree", "react"]

SINGLE_GOALS = [
    SingleTask(goal="fetch", object="mug"),
    SingleTask(goal="fetch", object="mug", target="table"),
    SingleTask(goal="deliver", object="book", target="desk"),
    SingleTask(goal="store", object="apple", target="refrigerator"),
    SingleTask(goal="place", object="mug", target="shelf"),
    SingleTask(goal="open", object="drawer"),
    SingleTask(goal="close", object="drawer"),
    SingleTask(goal="turn_on", object="lights"),
    SingleTask(goal="turn_off", object="tap"),
    SingleTask(goal="find", object="mug"),
    SingleTask(goal="navigate_to", target="fridge"),
]


def _ids(tasks):
    return [t.goal + ("-dest" if t.target else "") for t in tasks]


def _start_state(task: SingleTask) -> WorldState:
    state = WorldState.initial()
    if task.goal == "close":
        state.object(str(task.object)).is_open = (
            True  # only an open thing can be closed
        )
    return state


@pytest.mark.parametrize("planner_type", PLANNERS)
@pytest.mark.parametrize("task", SINGLE_GOALS, ids=_ids(SINGLE_GOALS))
def test_every_planner_plans_every_library_goal(planner_type, task):
    result = create_planner(planner_type).plan(task, _start_state(task))
    assert result.success, (planner_type, task.goal, result.errors, result.validation)
    assert result.plan is not None and result.plan.steps
    assert result.validation is not None and result.validation.valid


def test_fetch_with_no_destination_brings_the_object_back_to_the_user():
    for planner_type in PLANNERS:
        result = create_planner(planner_type).plan(
            SingleTask(goal="fetch", object="mug"), WorldState.initial()
        )
        steps = [(s.action, s.target) for s in result.plan.steps]
        assert steps[-2:] == [("locate", "user"), ("navigate", "user")], planner_type
        assert ("pickup", "mug") in steps


def test_turn_on_and_off_plan_locate_navigate_toggle():
    for goal, action in (("turn_on", "turn_on"), ("turn_off", "turn_off")):
        result = create_planner("rule_based").plan(
            SingleTask(goal=goal, object="lights"), WorldState.initial()
        )
        assert [s.action for s in result.plan.steps] == ["locate", "navigate", action]
        assert result.validation.goal_satisfied is True


def test_already_on_means_nothing_to_do():
    state = WorldState.initial()
    state.object("lights").is_on = True
    result = create_planner("rule_based").plan(
        SingleTask(goal="turn_on", object="lights"), state
    )
    assert result.success and result.plan.steps == []
    assert "the lights is already on" in result.plan.metadata["skipped_steps"]


def test_unknown_state_can_still_be_turned_off():
    result = create_planner("rule_based").plan(
        SingleTask(goal="turn_off", object="tap"), WorldState.initial()
    )
    assert result.success


# -- multi-object composition ---------------------------------------------


MULTI = [
    SingleTask(goal="store", object="apple", target="refrigerator"),
    SingleTask(goal="place", object="mug", target="shelf"),
    SingleTask(goal="fetch", object="book", target="desk"),
]


@pytest.mark.parametrize("planner_type", PLANNERS)
def test_multi_object_plans_compose_from_the_single_goals(planner_type):
    result = create_planner(planner_type).plan_multi(MULTI, WorldState.initial())

    assert result.success, (planner_type, result.errors, result.validation)
    steps = [(s.action, s.target) for s in result.plan.steps]
    # The hand is empty again before each pickup: one carried at a time.
    pickups = [i for i, (a, _) in enumerate(steps) if a == "pickup"]
    assert [steps[i][1] for i in pickups] == ["apple", "mug", "book"]
    assert [s.step_id for s in result.plan.steps] == list(range(1, len(steps) + 1))
    assert result.plan.metadata["sub_goals"][0]["goal"] == "store"


@pytest.mark.parametrize("planner_type", PLANNERS)
def test_multi_object_plan_skips_what_the_state_already_satisfies(planner_type):
    state = WorldState.initial()
    state.object("apple").location = "refrigerator"
    result = create_planner(planner_type).plan_multi(MULTI[:2], state)

    assert result.success
    actions = [(s.action, s.target) for s in result.plan.steps]
    assert ("pickup", "apple") not in actions
    assert ("pickup", "mug") in actions


def test_a_sub_goal_that_cannot_be_planned_fails_with_a_plain_reason():
    bad = [MULTI[0], SingleTask(goal="store", object="mug")]  # no target
    result = create_planner("rule_based").plan_multi(bad, WorldState.initial())
    assert not result.success and result.plan is None
    assert result.errors[0].startswith("Step 2 of 2 (store):")


# -- falling back cleanly --------------------------------------------------


def test_htn_hands_an_unknown_goal_to_the_rule_based_planner_and_says_so():
    result = create_planner("htn").plan(
        SingleTask(goal="clean", object="window"), WorldState.initial()
    )
    # The fallback is tried and explained; its plan is then refused because
    # no executor action can do "clean".
    assert not result.success
    fallback = result.plan.metadata["planner_fallback"]
    assert fallback["requested"] == "htn" and fallback["used"] == "rule_based"
    assert "no method for 'clean'" in fallback["reason"]


def test_htn_without_a_fallback_explains_in_plain_language():
    from planner.htn import HTNPlanner

    result = HTNPlanner().plan(
        SingleTask(goal="clean", object="window"), WorldState.initial()
    )
    assert not result.success
    assert "doesn't know how to 'clean'" in result.errors[0]
    assert "rule-based planner" in result.errors[0]


# -- the library itself -------------------------------------------------------


def test_library_covers_every_task_kind_the_brief_asks_for():
    ids = {k.id for k in TASK_LIBRARY}
    assert {
        "fetch",
        "deliver",
        "put",
        "open_close",
        "toggle",
        "find",
        "clear_table",
        "tidy_up",
    } <= ids
    assert COMPOSITE_GOALS == {"clear_table", "tidy_up"}


def test_library_serialises_with_examples_for_the_ui():
    entries = library_as_dicts()
    assert all(e["title"] and e["summary"] and e["examples"] for e in entries)
    assert capabilities_sentence().startswith("I can ")

"""
test_planner_htn.py

Purpose
-------
Unit tests for `planner/htn.py`: the decomposition engine itself
(primitive vs. compound task handling, method selection/fallback,
recursive expansion), `HTNPlanner`'s goal coverage for slice 1
(tier1_locate/tier2_pickup/tier3_store shapes), and its `Planner`
interface conformance. See `docs/architecture/planning.md`'s "HTN
planner" section for the design this implements.

How to run
-----------
    cd backend
    python -m pytest tests/test_planner_htn.py -v
"""

from planner.exceptions import UnsupportedGoalError
from planner.htn import (
    METHOD_LIBRARY,
    CompoundTask,
    HTNPlanner,
    Method,
    PrimitiveTask,
    _decompose,
    _StepBuilder,
)
from planner.state import WorldState
from schemas.task import SingleTask

# ----------------------------------------------------------------------
# Engine: primitive/compound task handling, method selection, recursion
# ----------------------------------------------------------------------


def test_primitive_task_is_emitted_directly():
    builder = _StepBuilder()
    _decompose(PrimitiveTask("locate", "mug"), WorldState.initial(), builder)
    assert len(builder.steps) == 1
    assert builder.steps[0].action == "locate"
    assert builder.steps[0].target == "mug"


def test_compound_task_recurses_through_its_method():
    builder = _StepBuilder()
    _decompose(
        CompoundTask("LocateObject", {"obj": "mug"}), WorldState.initial(), builder
    )
    actions = [(s.action, s.target) for s in builder.steps]
    assert actions == [("locate", "mug"), ("navigate", "mug")]


def test_method_selection_tries_methods_in_order_first_match_wins():
    calls = []

    def precondition_a(_state, _args):
        calls.append("a")
        return False

    def precondition_b(_state, _args):
        calls.append("b")
        return True

    library = {
        "TestTask": [
            Method("a", precondition_a, lambda args: [PrimitiveTask("locate", "x")]),
            Method("b", precondition_b, lambda args: [PrimitiveTask("navigate", "x")]),
        ]
    }
    original = METHOD_LIBRARY.get("TestTask")
    METHOD_LIBRARY["TestTask"] = library["TestTask"]
    try:
        builder = _StepBuilder()
        _decompose(CompoundTask("TestTask"), WorldState.initial(), builder)
        assert calls == ["a", "b"]
        assert builder.steps[0].action == "navigate"
    finally:
        if original is None:
            del METHOD_LIBRARY["TestTask"]
        else:
            METHOD_LIBRARY["TestTask"] = original


def test_no_applicable_method_raises_unsupported_goal_error():
    library = {"AlwaysFails": [Method("f", lambda s, a: False, lambda a: [])]}
    METHOD_LIBRARY["AlwaysFails"] = library["AlwaysFails"]
    try:
        builder = _StepBuilder()
        try:
            _decompose(CompoundTask("AlwaysFails"), WorldState.initial(), builder)
            assert False, "expected UnsupportedGoalError"
        except UnsupportedGoalError:
            pass
    finally:
        del METHOD_LIBRARY["AlwaysFails"]


def test_unknown_compound_task_name_raises_unsupported_goal_error():
    builder = _StepBuilder()
    try:
        _decompose(CompoundTask("NoSuchTask"), WorldState.initial(), builder)
        assert False, "expected UnsupportedGoalError"
    except UnsupportedGoalError:
        pass


def test_recursive_expansion_reaches_only_primitives():
    """AcquireObject -> LocateObject (compound) + PickUp (primitive) --
    confirms multi-level recursion, not a single flat lookup."""
    builder = _StepBuilder()
    _decompose(
        CompoundTask("AcquireObject", {"obj": "mug"}), WorldState.initial(), builder
    )
    actions = [s.action for s in builder.steps]
    assert actions == ["locate", "navigate", "pickup"]


# ----------------------------------------------------------------------
# HTNPlanner: goal coverage for slice 1 (tier1/tier2/tier3 shapes)
# ----------------------------------------------------------------------


def test_find_goal_produces_locate_navigate():
    task = SingleTask(goal="find", object="mug")
    result = HTNPlanner().plan(task, WorldState.initial())
    assert result.success
    assert [(s.action, s.target) for s in result.plan.steps] == [
        ("locate", "mug"),
        ("navigate", "mug"),
    ]


def test_pick_up_goal_produces_locate_navigate_pickup():
    task = SingleTask(goal="pick_up", object="mug")
    result = HTNPlanner().plan(task, WorldState.initial())
    assert result.success
    assert [(s.action, s.target) for s in result.plan.steps] == [
        ("locate", "mug"),
        ("navigate", "mug"),
        ("pickup", "mug"),
    ]


def test_store_goal_matches_rule_based_and_behavior_tree_sequence():
    """Same task/state `test_planner_behavior_tree.py`'s equivalent
    test uses -- HTNPlanner should decompose to the identical primitive
    sequence via its own independent method library."""
    task = SingleTask(goal="store", object="apple", target="refrigerator")
    result = HTNPlanner().plan(task, WorldState.initial())
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


def test_store_goal_skips_open_close_for_known_non_openable_target():
    state = WorldState.initial()
    state.object("shelf").is_openable = False
    task = SingleTask(goal="store", object="book", target="shelf")
    result = HTNPlanner().plan(task, state)
    assert result.success
    actions = [s.action for s in result.plan.steps]
    assert "open" not in actions
    assert "close" not in actions
    assert actions.count("place") == 1


def test_store_goal_skips_open_close_when_target_already_open():
    state = WorldState.initial()
    state.object("drawer").is_open = True
    task = SingleTask(goal="store", object="cd", target="drawer")
    result = HTNPlanner().plan(task, state)
    assert result.success
    actions = [s.action for s in result.plan.steps]
    assert "open" not in actions
    assert "close" not in actions


def test_place_goal_without_container_semantics_skips_open_close():
    task = SingleTask(goal="place", object="pen", target="table")
    result = HTNPlanner().plan(task, WorldState.initial())
    assert result.success
    actions = [s.action for s in result.plan.steps]
    assert "open" not in actions
    assert "close" not in actions
    assert actions[-1] == "place"


def test_open_goal_produces_locate_navigate_open():
    task = SingleTask(goal="open", object="fridge")
    result = HTNPlanner().plan(task, WorldState.initial())
    assert result.success
    assert [(s.action, s.target) for s in result.plan.steps] == [
        ("locate", "fridge"),
        ("navigate", "fridge"),
        ("open", "fridge"),
    ]


def test_close_goal_produces_locate_navigate_close():
    # close's own precondition requires is_open is True -- a fresh
    # state (is_open=None, unknown) correctly fails validation here,
    # the same way it would for any other planner's "close" goal.
    state = WorldState.initial()
    state.object("fridge").is_open = True
    task = SingleTask(goal="close", object="fridge")
    result = HTNPlanner().plan(task, state)
    assert result.success
    assert [(s.action, s.target) for s in result.plan.steps] == [
        ("locate", "fridge"),
        ("navigate", "fridge"),
        ("close", "fridge"),
    ]


def test_unsupported_goal_fails_planning_result_not_raises():
    task = SingleTask(goal="fetch", object="mug", target="table")
    result = HTNPlanner().plan(task, WorldState.initial())
    assert result.success is False
    assert result.plan is None
    assert result.errors


def test_missing_required_field_fails_planning_result():
    task = SingleTask(goal="store", object="mug")  # no target
    result = HTNPlanner().plan(task, WorldState.initial())
    assert result.success is False
    assert result.errors


# ----------------------------------------------------------------------
# Planner interface conformance
# ----------------------------------------------------------------------


def test_htn_planner_type_is_htn():
    assert HTNPlanner.planner_type == "htn"


def test_htn_planner_result_has_consistent_schema():
    task = SingleTask(goal="pick_up", object="mug")
    result = HTNPlanner().plan(task, WorldState.initial())
    assert result.planner_type == "htn"
    assert result.success is True
    assert result.plan is not None
    assert result.validation is not None
    assert result.validation.valid is True
    assert result.latency_ms >= 0


def test_htn_planner_accepts_memory_context_parameter_unused():
    """Interface conformance: every strategy must accept
    `memory_context` even if unused -- see planner.py's docstring."""
    task = SingleTask(goal="pick_up", object="mug")
    result = HTNPlanner().plan(task, WorldState.initial(), memory_context=None)
    assert result.success is True

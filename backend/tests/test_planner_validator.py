"""
test_planner_validator.py

Purpose
-------
Unit tests for `planner/validator.py`'s `PlanValidator`. Covers section
14's "Plan validation" bullets: a valid plan, a plan with a missing
step, incorrect ordering, an impossible action, an unmet precondition,
and a goal not satisfied by the final state.

How to run
-----------
    cd backend
    python -m pytest tests/test_planner_validator.py -v
"""

from planner.models import Plan, PlanStep
from planner.rule_based import RuleBasedPlanner
from planner.state import WorldState
from planner.validator import PlanValidator
from schemas.task import SingleTask

VALIDATOR = PlanValidator()
TASK = SingleTask(goal="store", object="apple", target="refrigerator")


def _plan(steps):
    return Plan(task_id="t1", planner_type="rule_based", goal_summary={}, steps=steps)


def test_valid_plan_from_rule_based_planner_passes():
    result = RuleBasedPlanner().plan(TASK, WorldState.initial())
    assert result.validation.valid
    assert result.validation.error_count == 0
    assert result.validation.goal_satisfied is True


def test_missing_step_leaves_goal_unsatisfied():
    # Never picks up or places the apple -- goal cannot be satisfied.
    steps = [
        PlanStep(
            step_id=1, action="locate", target="apple", description="Locate apple"
        ),
        PlanStep(
            step_id=2,
            action="navigate",
            target="apple",
            description="Navigate to apple",
        ),
    ]
    result = VALIDATOR.validate(_plan(steps), TASK, WorldState.initial())
    assert not result.valid
    assert any(i.code == "goal_not_satisfied" for i in result.issues)


def test_incorrect_ordering_close_before_open_fails():
    steps = [
        PlanStep(
            step_id=1, action="locate", target="refrigerator", description="Locate"
        ),
        PlanStep(
            step_id=2, action="navigate", target="refrigerator", description="Navigate"
        ),
        PlanStep(step_id=3, action="close", target="refrigerator", description="Close"),
    ]
    result = VALIDATOR.validate(_plan(steps), TASK, WorldState.initial())
    assert not result.valid
    assert any(
        i.code == "precondition_failed" and i.step_id == 3 for i in result.issues
    )


def test_impossible_unknown_action():
    steps = [
        PlanStep(step_id=1, action="teleport", target="apple", description="Teleport")
    ]
    result = VALIDATOR.validate(_plan(steps), TASK, WorldState.initial())
    assert not result.valid
    assert result.issues[0].code == "unknown_action"


def test_unmet_precondition_pickup_without_navigate():
    steps = [
        PlanStep(
            step_id=1, action="locate", target="apple", description="Locate apple"
        ),
        PlanStep(
            step_id=2, action="pickup", target="apple", description="Pick up apple"
        ),
    ]
    result = VALIDATOR.validate(_plan(steps), TASK, WorldState.initial())
    assert not result.valid
    assert any(
        i.code == "precondition_failed" and i.step_id == 2 for i in result.issues
    )


def test_place_before_pickup_fails_precondition():
    steps = [
        PlanStep(
            step_id=1,
            action="place",
            target="apple",
            parameters={"container": "refrigerator"},
            description="Place apple",
        )
    ]
    result = VALIDATOR.validate(_plan(steps), TASK, WorldState.initial())
    assert not result.valid
    assert result.issues[0].code == "precondition_failed"


def test_missing_required_parameter_for_place():
    steps = [
        PlanStep(step_id=1, action="place", target="apple", description="Place apple")
    ]
    result = VALIDATOR.validate(_plan(steps), TASK, WorldState.initial())
    assert not result.valid
    assert any(i.code == "missing_parameter" for i in result.issues)


def test_duplicate_consecutive_step_flagged_as_warning_not_error():
    find_task = SingleTask(goal="find", object="apple")
    steps = [
        PlanStep(
            step_id=1, action="locate", target="apple", description="Locate apple"
        ),
        PlanStep(
            step_id=2, action="locate", target="apple", description="Locate apple"
        ),
    ]
    result = VALIDATOR.validate(_plan(steps), find_task, WorldState.initial())
    duplicate_issues = [i for i in result.issues if i.code == "duplicate_step"]
    assert len(duplicate_issues) == 1
    assert duplicate_issues[0].severity == "warning"
    assert result.valid


def test_goal_with_no_registered_check_is_unverifiable_not_invalid():
    task = SingleTask(goal="turn_on", object="lamp")
    steps = [
        PlanStep(step_id=1, action="locate", target="lamp", description="Locate lamp"),
        PlanStep(
            step_id=2, action="navigate", target="lamp", description="Navigate to lamp"
        ),
        PlanStep(
            step_id=3,
            action="act",
            target="lamp",
            parameters={"action": "turn_on"},
            description="Act",
        ),
    ]
    result = VALIDATOR.validate(_plan(steps), task, WorldState.initial())
    assert result.valid
    assert result.goal_satisfied is None

"""
test_planner_models.py

Purpose
-------
Unit tests for `planner/models.py`'s data model: `PlanStep`, `Plan`,
`ValidationIssue`, `ValidationResult`, `PlanningResult`, and their enum
fields. Confirms construction succeeds for well-formed data and that
`extra="forbid"`/field constraints reject malformed data, matching this
project's schema-testing convention (`tests/test_task.py`).

How to run
-----------
    cd backend
    python -m pytest tests/test_planner_models.py -v
"""

import pytest
from pydantic import ValidationError

from planner.models import (
    Plan,
    PlanningResult,
    PlanStatus,
    PlanStep,
    StepStatus,
    ValidationIssue,
    ValidationResult,
)


def test_plan_step_valid_construction():
    step = PlanStep(
        step_id=1, action="locate", target="apple", description="Locate apple"
    )
    assert step.status == StepStatus.PENDING
    assert step.parameters == {}


def test_plan_step_rejects_unknown_field():
    with pytest.raises(ValidationError):
        PlanStep(
            step_id=1, action="locate", target="apple", description="x", bogus="nope"
        )


def test_plan_step_rejects_non_positive_step_id():
    with pytest.raises(ValidationError):
        PlanStep(step_id=0, action="locate", target="apple", description="x")


def test_plan_valid_construction_and_step_count():
    step = PlanStep(
        step_id=1, action="locate", target="apple", description="Locate apple"
    )
    plan = Plan(
        task_id="t1",
        planner_type="rule_based",
        goal_summary={"goal": "find", "object": "apple"},
        steps=[step],
    )
    assert plan.status == PlanStatus.DRAFT
    assert plan.step_count == 1
    assert plan.plan_id  # auto-generated


def test_plan_malformed_missing_required_field():
    with pytest.raises(ValidationError):
        Plan(planner_type="rule_based", goal_summary={})  # missing task_id


def test_validation_result_counts_by_severity():
    result = ValidationResult(
        valid=False,
        issues=[
            ValidationIssue(
                step_id=1, code="precondition_failed", message="x", severity="error"
            ),
            ValidationIssue(
                step_id=2, code="duplicate_step", message="y", severity="warning"
            ),
        ],
    )
    assert result.error_count == 1
    assert result.warning_count == 1


def test_planning_result_success_without_plan():
    result = PlanningResult(
        success=False, planner_type="rule_based", latency_ms=1.0, errors=["no plan"]
    )
    assert result.plan is None
    assert result.errors == ["no plan"]

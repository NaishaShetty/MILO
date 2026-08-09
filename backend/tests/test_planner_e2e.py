"""
test_planner_e2e.py

Purpose
-------
Section 28's "End-to-end planning test": Structured intent -> Planner ->
Validator -> Validated plan, entirely in-process, with NO AI2-THOR and
NO live LLM required. Starts from a `SingleTask` shaped exactly like
what `LanguageAgent.parse()` (Phase 3) would hand a Planner -- this
test does not call the Language runtime itself (that requires network
access / a configured provider and is already covered by
`backend/tests/test_language_*`), but it proves the Phase 3 -> Phase 4
boundary: any `SingleTask` satisfying `schemas/task.py`'s contract can
be planned, validated, and produces a `PlanningResult` ready for a
(not-yet-built) Phase 5 to consume.

How to run
-----------
    cd backend
    python -m pytest tests/test_planner_e2e.py -v
"""

from planner.factory import PlannerType, create_planner
from planner.models import PlanStatus
from planner.state import WorldState
from schemas.task import SingleTask


def test_full_pipeline_instruction_shaped_intent_to_validated_plan():
    # Shaped exactly like LanguageAgent.parse()'s output for
    # "Put the apple in the refrigerator."
    task = SingleTask(goal="store", object="apple", target="refrigerator")

    planner = create_planner(PlannerType.RULE_BASED)
    result = planner.plan(task, WorldState.initial())

    assert result.success
    assert result.plan.status == PlanStatus.VALID
    assert result.validation.valid
    assert result.validation.goal_satisfied is True
    # This is exactly what a Phase 5 Execution Controller is expected
    # to receive: an ordered, validated, simulator-independent step list.
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


def test_full_pipeline_all_three_strategies_agree_on_success():
    task = SingleTask(goal="pick_up", object="mug")
    for planner_type in PlannerType:
        result = create_planner(planner_type).plan(task, WorldState.initial())
        assert result.success, f"{planner_type} failed to produce a valid plan"


def test_full_pipeline_multitask_subtasks_are_planned_individually():
    from schemas.task import MultiTask

    multi = MultiTask(
        subtasks=[
            SingleTask(goal="pick_up", object="cup"),
            SingleTask(goal="store", object="cup", target="cabinet"),
        ]
    )
    planner = create_planner(PlannerType.RULE_BASED)
    results = [planner.plan(sub, WorldState.initial()) for sub in multi.subtasks]
    assert all(r.success for r in results)

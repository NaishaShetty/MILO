"""
test_planner_evaluation.py

Purpose
-------
Unit tests for `planner/evaluation.py`'s `PlannerEvaluator`: metric
collection for a single planner run, multi-planner comparison, and a
failed planning run reporting its failure rather than crashing the
evaluator.

How to run
-----------
    cd backend
    python -m pytest tests/test_planner_evaluation.py -v
"""

from planner.evaluation import PlannerEvaluator
from planner.factory import PlannerType, create_planner
from planner.rule_based import RuleBasedPlanner
from planner.state import WorldState
from schemas.task import SingleTask

EVALUATOR = PlannerEvaluator()


def test_metric_collection_for_a_successful_run():
    task = SingleTask(goal="store", object="apple", target="refrigerator")
    metrics = EVALUATOR.evaluate(RuleBasedPlanner(), task, WorldState.initial())
    assert metrics.planner_type == "rule_based"
    assert metrics.success is True
    assert metrics.valid is True
    assert metrics.goal_satisfied is True
    assert metrics.step_count == 8
    assert metrics.invalid_action_count == 0
    assert metrics.latency_ms >= 0


def test_planner_comparison_returns_one_metric_per_planner():
    task = SingleTask(goal="pick_up", object="mug")
    planners = {t.value: create_planner(t) for t in PlannerType}
    results = EVALUATOR.compare(planners, task, WorldState.initial())
    assert {m.planner_type for m in results} == {
        "rule_based",
        "react",
        "behavior_tree",
        "htn",
    }
    assert all(m.success for m in results)


def test_failed_planning_run_is_reported_not_raised():
    task = SingleTask(
        goal="store"
    )  # missing object/target -> InvalidTaskError internally
    metrics = EVALUATOR.evaluate(RuleBasedPlanner(), task, WorldState.initial())
    assert metrics.success is False
    assert metrics.valid is False
    assert metrics.step_count == 0
    assert metrics.error is not None


def test_evaluate_clones_state_so_runs_do_not_interfere():
    shared_state = WorldState.initial()
    task = SingleTask(goal="pick_up", object="mug")
    EVALUATOR.evaluate(RuleBasedPlanner(), task, shared_state)
    # The shared state passed in must remain untouched by the run.
    assert not shared_state.has_seen("mug")

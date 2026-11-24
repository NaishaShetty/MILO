"""
test_planner_resume.py

Regression tests for resumable planning (`planner/progress.py`):

- every planner skips steps the current `WorldState` already satisfies,
  so a replan after partial progress never re-emits `pickup` (which the
  validator rejects once the robot is already holding the object);
- end to end through `Orchestrator`, a replan after the pickup succeeded
  and a retry after several steps completed both finish the task instead
  of failing or re-running finished work.

Simulator-free: `FakeSimulator` + the real planners, no LLM.
"""

from __future__ import annotations

import pytest
from _execution_test_helpers import FakeSimulator, apple_and_fridge_scene

from agents.execution_agent import ExecutionAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from agents.task_state import TaskStatus
from execution.models import ExecutionStatus
from orchestration.orchestrator import Orchestrator
from planner.factory import create_planner
from planner.progress import prune_satisfied_steps
from planner.state import WorldState
from schemas.task import SingleTask

PLANNERS = ["rule_based", "htn", "behavior_tree", "react"]
STORE = SingleTask(goal="store", object="apple", target="refrigerator")


def _holding_apple_state() -> WorldState:
    state = WorldState.initial()
    state.robot_holding = "apple"
    apple = state.object("apple")
    apple.is_held = True
    apple.is_located = True
    apple.is_near_robot = True
    return state


def _actions(result):
    return [(s.action, s.target) for s in result.plan.steps]


@pytest.mark.parametrize("planner_type", PLANNERS)
def test_replan_after_pickup_succeeded_does_not_re_emit_the_pickup(planner_type):
    result = create_planner(planner_type).plan(STORE, _holding_apple_state())

    assert result.success, result.errors
    steps = _actions(result)
    assert ("pickup", "apple") not in steps
    assert ("locate", "apple") not in steps and ("navigate", "apple") not in steps
    # It carries straight on to the fridge and finishes the job.
    assert steps[0] == ("locate", "refrigerator")
    assert ("place", "apple") in steps
    assert result.validation is not None and result.validation.goal_satisfied is True
    assert [s.step_id for s in result.plan.steps] == list(
        range(1, len(result.plan.steps) + 1)
    )
    assert result.plan.metadata["skipped_steps"] == ["already holding the apple"]


@pytest.mark.parametrize("planner_type", PLANNERS)
def test_a_plan_from_scratch_is_unchanged(planner_type):
    result = create_planner(planner_type).plan(STORE, WorldState.initial())

    assert result.success
    assert len(result.plan.steps) == 8
    assert "skipped_steps" not in result.plan.metadata


@pytest.mark.parametrize("planner_type", ["rule_based", "htn", "behavior_tree"])
def test_door_already_open_is_not_opened_again(planner_type):
    state = WorldState.initial()
    state.object("refrigerator").is_open = True
    result = create_planner(planner_type).plan(
        SingleTask(goal="open", object="refrigerator"), state
    )

    assert result.success
    assert result.plan.steps == []  # nothing left to do
    assert "the refrigerator is already open" in result.plan.metadata["skipped_steps"]


@pytest.mark.parametrize("planner_type", ["rule_based", "htn", "behavior_tree"])
def test_object_already_placed_leaves_nothing_to_do(planner_type):
    state = WorldState.initial()
    apple = state.object("apple")
    apple.location = "refrigerator"
    result = create_planner(planner_type).plan(STORE, state)

    assert result.success
    assert result.plan.steps == []
    assert result.validation is not None and result.validation.goal_satisfied is True


def test_prune_leaves_unrelated_steps_alone():
    result = create_planner("rule_based").plan(STORE, WorldState.initial())
    steps, skipped = prune_satisfied_steps(result.plan.steps, WorldState.initial())
    assert skipped == []
    assert len(steps) == 8


# -- end to end through the Orchestrator ---------------------------------


def _orchestrator(sim):
    return Orchestrator(
        PlannerAgentWrapper(create_planner("rule_based")), ExecutionAgentWrapper(sim)
    )


def test_replan_after_the_pickup_succeeded_finishes_the_task():
    # The robot picks the apple up, then the walk to the fridge fails
    # once (a "replan" verdict). The new plan must not pick the apple up
    # a second time.
    navigates = {"n": 0}

    def fail_second_navigate() -> None:
        navigates["n"] += 1
        if navigates["n"] == 2:  # navigate to the fridge, after the pickup
            sim._fail_actions.add("navigate")
        elif navigates["n"] == 3:
            sim._fail_actions.discard("navigate")

    sim = FakeSimulator(
        objects=apple_and_fridge_scene(), hooks={"navigate": fail_second_navigate}
    )

    task_state = _orchestrator(sim).run(STORE)

    assert task_state.status == TaskStatus.SUCCEEDED, task_state.failures
    assert len(task_state.execution_history) == 2
    assert task_state.execution_history[0].status == ExecutionStatus.FAILED
    assert task_state.execution_history[1].status == ExecutionStatus.SUCCESS
    pickups = [c for c in sim.calls if c["action"] == "pickup"]
    assert len(pickups) == 1
    assert sim.inventory_objects == []  # the apple ended up in the fridge


def test_retry_after_partial_progress_does_not_re_run_finished_steps():
    # `open` fails once (step 6 of 8) with a transient error -> the
    # reflection verdict is "retry" and the same plan is re-executed.
    # Steps 1-5 (including the pickup) already succeeded and must be
    # skipped; only open/place/close run the second time.
    opens = {"n": 0}

    def flaky_open() -> None:
        opens["n"] += 1
        if opens["n"] >= 2:
            sim._fail_actions.discard("open")

    sim = FakeSimulator(
        objects=apple_and_fridge_scene(),
        fail_actions={"open"},
        hooks={"open": flaky_open},
    )

    task_state = _orchestrator(sim).run(STORE)

    assert task_state.status == TaskStatus.SUCCEEDED, task_state.failures
    assert len(task_state.execution_history) == 2
    assert task_state.execution_history[0].status == ExecutionStatus.FAILED
    assert task_state.execution_history[1].status == ExecutionStatus.SUCCESS
    pickups = [c for c in sim.calls if c["action"] == "pickup"]
    assert len(pickups) == 1
    second_attempt_actions = [
        s.action
        for s in task_state.execution_history[1].step_results
        if s.status.value == "completed"
    ]
    assert len(second_attempt_actions) == 8  # all done in the end
    assert task_state.completed_steps == [1, 2, 3, 4, 5, 6, 7, 8]


def test_a_goal_that_is_already_true_succeeds_without_acting():
    sim = FakeSimulator(objects=apple_and_fridge_scene())
    orchestrator = _orchestrator(sim)
    # Nothing to do for "open the fridge" if it is already open -- but
    # the Orchestrator starts from `WorldState.initial()`, so seed the
    # state through a planner that reports an empty plan.
    planner = create_planner("rule_based")

    class _AlreadyDone(PlannerAgentWrapper):
        def plan(self, task, state, memory_context=None):
            state.object("refrigerator").is_open = True
            return super().plan(task, state, memory_context)

    orchestrator = Orchestrator(_AlreadyDone(planner), ExecutionAgentWrapper(sim))
    task_state = orchestrator.run(SingleTask(goal="open", object="refrigerator"))

    assert task_state.status == TaskStatus.SUCCEEDED
    assert sim.calls == []
    assert task_state.execution_history == []

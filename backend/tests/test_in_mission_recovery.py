"""In-mission recovery: look around after "not visible", walk up again after
"not reachable" -- in the same mission, behind MILO_INMISSION_RECOVERY."""

from __future__ import annotations

from typing import Dict, Tuple

from agents.execution_agent import ExecutionAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from benchmark.run import run_case
from benchmark.suite import fault_cases
from execution.errors import ExecutionError, ExecutionErrorCode
from execution.models import ExecutionRecord, StepExecutionRecord, StepStatus
from learning.synthetic import Faults, SyntheticSimulator
from novel.eval_novel import scene
from orchestration import recovery
from orchestration.orchestrator import Orchestrator
from planner.factory import create_planner
from planner.models import Plan, PlanStep
from schemas.task import SingleTask


def _plan() -> Plan:
    steps = [
        PlanStep(step_id=1, action="locate", target="apple", description="Find apple"),
        PlanStep(step_id=2, action="navigate", target="apple", description="Go"),
        PlanStep(step_id=3, action="pickup", target="apple", description="Pick"),
    ]
    steps[0].status = StepStatus.COMPLETED
    steps[1].status = StepStatus.COMPLETED
    steps[2].status = StepStatus.FAILED
    return Plan(
        plan_id="p",
        task_id="t",
        planner_type="rule_based",
        goal_summary={"goal": "fetch"},
        steps=steps,
    )


def _record(message: str) -> ExecutionRecord:
    results = [
        StepExecutionRecord(
            step_id=1, action="locate", target="apple", status=StepStatus.COMPLETED
        ),
        StepExecutionRecord(
            step_id=2, action="navigate", target="apple", status=StepStatus.COMPLETED
        ),
        StepExecutionRecord(
            step_id=3,
            action="pickup",
            target="apple",
            status=StepStatus.FAILED,
            error=ExecutionError(
                code=ExecutionErrorCode.SIMULATOR_ERROR, message=message, step_id=3
            ),
        ),
    ]
    return ExecutionRecord(plan_id="p", task_id="t", step_results=results)


def test_not_visible_inserts_a_look_around_before_the_failed_step():
    plan = _plan()
    counts: Dict[Tuple[str, str, str], int] = {}
    said = recovery.mitigate(
        plan, _record("cannot pick up: object not visible"), counts
    )
    assert said and "look around" in said
    assert [s.action for s in plan.steps] == [
        "locate",
        "navigate",
        "look_around",
        "pickup",
    ]
    assert [s.step_id for s in plan.steps] == [1, 2, 3, 4]
    assert plan.steps[1].status == StepStatus.COMPLETED  # already-done steps stay done


def test_not_reachable_re_approaches_then_tries_another_side():
    plan = _plan()
    counts: Dict[Tuple[str, str, str], int] = {}
    record = _record("cannot pick up: object not reachable")
    assert recovery.mitigate(plan, record, counts)
    assert [s.action for s in plan.steps] == [
        "locate",
        "navigate",
        "navigate",
        "pickup",
    ]
    assert (
        plan.steps[2].status == StepStatus.PENDING and plan.steps[2].target == "apple"
    )
    assert "another side" in (recovery.mitigate(plan, record, counts) or "")
    assert [s.action for s in plan.steps][3:] == ["look_around", "navigate", "pickup"]
    assert recovery.mitigate(plan, record, counts) is None  # bounded per step


def test_other_failures_are_left_to_plain_retry_or_replan():
    plan = _plan()
    counts: Dict[Tuple[str, str, str], int] = {}
    assert recovery.mitigate(plan, _record("path blocked"), counts) is None
    assert len(plan.steps) == 3


def test_the_flag_turns_it_off(monkeypatch):
    monkeypatch.setenv("MILO_INMISSION_RECOVERY", "0")
    assert recovery.enabled() is False
    monkeypatch.setenv("MILO_INMISSION_RECOVERY", "1")
    assert recovery.enabled() is True


def test_both_fault_kinds_now_recover_in_the_same_mission():
    for fault in ("wrong_detection", "out_of_reach"):
        case = next(c for c in fault_cases() if c.fault == fault)
        assert run_case(case, "rule_based")["success"] is True, fault
        assert run_case(case, "rule_based", recovery=False)["success"] is False, fault


def test_a_permanent_wrong_detection_is_handled_in_the_first_mission():
    def run(on: bool) -> str:
        sim = SyntheticSimulator(
            scene(), Faults(kind="wrong_detection", target="apple", times=99)
        )
        orch = Orchestrator(
            PlannerAgentWrapper(create_planner("rule_based")),
            ExecutionAgentWrapper(sim),  # type: ignore[arg-type]
            in_mission_recovery=on,
        )
        state = orch.run(SingleTask(goal="fetch", object="apple"), max_replans=1)
        if on:
            assert any("look around" in t["text"] for t in state.thoughts)
        return state.status.value

    assert run(True) == "succeeded"
    assert run(False) == "failed"

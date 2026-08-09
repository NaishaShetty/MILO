"""
test_orchestration_orchestrator.py

Purpose
-------
Integration tests for `orchestration.orchestrator.Orchestrator`'s
dynamic replanning loop (section 7.13): a task that succeeds on the
first attempt (parity with a single `TaskRunner`-style attempt), a
task whose first plan hits a recoverable navigation failure and
succeeds after one reflect -> replan -> continue cycle (preserving the
already-mutated `WorldState` rather than restarting), and a task that
exhausts `max_replans` and ends `FAILED`. Runs entirely against
`FakeSimulator` + `RuleBasedPlanner` -- zero AI2-THOR/LLM dependency,
matching `test_orchestration_task_runner.py`'s existing discipline.
"""

from __future__ import annotations

import threading
import time

from _execution_test_helpers import FakeSimulator

from agents.events import EventType
from agents.execution_agent import ExecutionAgentWrapper
from agents.failures import FailureCategory
from agents.memory_agent import MemoryAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from agents.registry import AgentRegistry
from agents.task_state import TaskStatus
from agents.vision_agent import VisionAgentWrapper
from execution.models import ExecutionStatus
from memory.agent import MemoryAgent
from memory.config import MemoryConfig
from orchestration.orchestrator import Orchestrator
from planner.rule_based import RuleBasedPlanner
from scene.detection import Detection
from scene.scene import Scene
from schemas.task import SingleTask


def _mug_table_scene():
    return [
        {
            "objectId": "Mug|1",
            "objectType": "Mug",
            "distance": 1.0,
            "isOpen": None,
            "parentReceptacle": "Table|1",
        },
        {"objectId": "Table|1", "objectType": "Table", "distance": 2.0, "isOpen": None},
    ]


def _fridge_scene():
    return [
        {
            "objectId": "Fridge|1",
            "objectType": "Fridge",
            "distance": 1.0,
            "isOpen": False,
        }
    ]


def _memory_agent(tmp_path):
    config = MemoryConfig(
        enabled=True,
        database_path=tmp_path / "memory.db",
        vector_store_path=tmp_path / "vector_store",
    )
    return MemoryAgentWrapper(MemoryAgent.from_config(config))


def test_task_succeeds_on_first_attempt(tmp_path):
    registry = AgentRegistry()
    orchestrator = Orchestrator(
        PlannerAgentWrapper(RuleBasedPlanner()),
        ExecutionAgentWrapper(FakeSimulator(objects=_mug_table_scene())),
        memory_agent=_memory_agent(tmp_path),
        registry=registry,
    )

    task_state = orchestrator.run(SingleTask(goal="find", object="mug"))

    assert task_state.status == TaskStatus.SUCCEEDED
    assert len(task_state.execution_history) == 1
    assert task_state.failures == []
    events = [e.event for e in orchestrator.events.get_events(task_state.task_id)]
    assert events[0] == EventType.TASK_CREATED
    assert EventType.TASK_COMPLETED in events
    assert EventType.REPLAN_TRIGGERED not in events
    assert registry.snapshot_states()  # agents were registered


def test_recoverable_navigation_failure_triggers_replan_then_succeeds(tmp_path):
    calls = {"navigate": 0}

    def clear_after_first_attempt() -> None:
        calls["navigate"] += 1
        if calls["navigate"] >= 2:
            sim._fail_actions.discard("navigate")

    sim = FakeSimulator(
        objects=_fridge_scene(),
        fail_actions={"navigate"},
        hooks={"navigate": clear_after_first_attempt},
    )
    orchestrator = Orchestrator(
        PlannerAgentWrapper(RuleBasedPlanner()),
        ExecutionAgentWrapper(sim),
        memory_agent=_memory_agent(tmp_path),
    )

    task_state = orchestrator.run(SingleTask(goal="find", object="fridge"))

    assert task_state.status == TaskStatus.SUCCEEDED
    assert len(task_state.execution_history) == 2
    assert task_state.execution_history[0].status == ExecutionStatus.FAILED
    assert task_state.execution_history[1].status == ExecutionStatus.SUCCESS
    assert task_state.failures[0].category == FailureCategory.NAVIGATION_FAILURE
    events = [e.event for e in orchestrator.events.get_events(task_state.task_id)]
    assert EventType.REPLAN_TRIGGERED in events
    assert events.count(EventType.PLAN_CREATED) == 2
    assert EventType.TASK_COMPLETED in events


def test_exhausting_max_replans_ends_task_failed(tmp_path):
    sim = FakeSimulator(objects=_fridge_scene(), fail_actions={"navigate"})
    orchestrator = Orchestrator(
        PlannerAgentWrapper(RuleBasedPlanner()),
        ExecutionAgentWrapper(sim),
        memory_agent=_memory_agent(tmp_path),
    )

    task_state = orchestrator.run(
        SingleTask(goal="find", object="fridge"), max_replans=1
    )

    assert task_state.status == TaskStatus.FAILED
    assert len(task_state.execution_history) == 2
    events = [e.event for e in orchestrator.events.get_events(task_state.task_id)]
    assert EventType.TASK_FAILED in events
    assert EventType.TASK_COMPLETED not in events


def test_orchestrator_works_without_a_memory_agent():
    orchestrator = Orchestrator(
        PlannerAgentWrapper(RuleBasedPlanner()),
        ExecutionAgentWrapper(FakeSimulator(objects=_mug_table_scene())),
    )
    task_state = orchestrator.run(SingleTask(goal="find", object="mug"))
    assert task_state.status == TaskStatus.SUCCEEDED
    assert task_state.retrieved_memories == []


def test_successful_task_records_latencies_metrics_and_created_memories(tmp_path):
    orchestrator = Orchestrator(
        PlannerAgentWrapper(RuleBasedPlanner()),
        ExecutionAgentWrapper(FakeSimulator(objects=_mug_table_scene())),
        memory_agent=_memory_agent(tmp_path),
    )

    task_state = orchestrator.run(SingleTask(goal="find", object="mug"))

    for key in (
        "planning_ms",
        "execution_ms",
        "memory_retrieval_ms",
        "memory_write_ms",
        "total_ms",
    ):
        assert key in task_state.latencies_ms
        assert task_state.latencies_ms[key] >= 0.0
    metrics = task_state.metrics()
    assert metrics["success"] is True
    assert metrics["actions"] > 0
    assert metrics["replans"] == 0
    assert len(task_state.created_memories) == 1
    assert task_state.created_memories[0]["memory_type"] == "episodic"


def test_on_created_callback_receives_the_live_mutating_task_state(tmp_path):
    orchestrator = Orchestrator(
        PlannerAgentWrapper(RuleBasedPlanner()),
        ExecutionAgentWrapper(FakeSimulator(objects=_mug_table_scene())),
        memory_agent=_memory_agent(tmp_path),
    )
    captured = {}

    def _on_created(task_state):
        captured["state"] = task_state
        assert task_state.status == TaskStatus.CREATED

    final_state = orchestrator.run(
        SingleTask(goal="find", object="mug"), on_created=_on_created
    )

    # Same object, mutated in place to its final status -- not a copy.
    assert captured["state"] is final_state
    assert captured["state"].status == TaskStatus.SUCCEEDED


def test_cancel_stops_a_run_blocked_mid_execution(tmp_path):
    gate = threading.Event()

    def _block_until_released() -> None:
        gate.wait(timeout=5.0)

    sim = FakeSimulator(
        objects=_fridge_scene(), hooks={"navigate": _block_until_released}
    )
    orchestrator = Orchestrator(
        PlannerAgentWrapper(RuleBasedPlanner()),
        ExecutionAgentWrapper(sim),
        memory_agent=_memory_agent(tmp_path),
    )
    result_holder = {}

    def _run():
        result_holder["state"] = orchestrator.run(
            SingleTask(goal="find", object="fridge")
        )

    thread = threading.Thread(target=_run)
    thread.start()
    time.sleep(0.05)  # let the background thread reach the blocking hook

    orchestrator.cancel()
    gate.set()
    thread.join(timeout=5.0)

    task_state = result_holder["state"]
    assert task_state.status == TaskStatus.CANCELLED
    events = [e.event for e in orchestrator.events.get_events(task_state.task_id)]
    assert EventType.TASK_CANCELLED in events
    assert EventType.TASK_FAILED not in events
    assert EventType.TASK_COMPLETED not in events
    # Cancellation must not write a memory -- section 3's explicit rule.
    assert task_state.created_memories == []


class _FakeVisionAgent:
    def __init__(self) -> None:
        scene = Scene()
        scene.add_detection(
            Detection(
                label="mug",
                confidence=0.9,
                bbox=[0, 0, 1, 1],
                position_3d=[1.0, 0.0, 2.0],
            )
        )
        self._scene = scene
        self.calls = 0

    def perceive(self, prompt: str) -> Scene:
        self.calls += 1
        return self._scene


def test_observe_step_populates_observations_when_vision_agent_configured(tmp_path):
    fake_vision = _FakeVisionAgent()
    orchestrator = Orchestrator(
        PlannerAgentWrapper(RuleBasedPlanner()),
        ExecutionAgentWrapper(FakeSimulator(objects=_mug_table_scene())),
        memory_agent=_memory_agent(tmp_path),
        vision_agent=VisionAgentWrapper(fake_vision),
    )

    task_state = orchestrator.run(SingleTask(goal="find", object="mug"))

    assert fake_vision.calls >= 1
    assert task_state.known_objects == ["mug"]
    assert task_state.observations[0]["label"] == "mug"
    assert "vision_ms" in task_state.latencies_ms
    events = [e.event for e in orchestrator.events.get_events(task_state.task_id)]
    assert EventType.OBSERVATION_RECEIVED in events


def test_observe_step_skipped_without_vision_agent_leaves_behavior_unchanged():
    orchestrator = Orchestrator(
        PlannerAgentWrapper(RuleBasedPlanner()),
        ExecutionAgentWrapper(FakeSimulator(objects=_mug_table_scene())),
    )
    task_state = orchestrator.run(SingleTask(goal="find", object="mug"))
    assert task_state.known_objects == []
    assert task_state.observations == []
    assert "vision_ms" not in task_state.latencies_ms


def test_observe_step_failure_does_not_break_the_task(tmp_path):
    class _BrokenVisionAgent:
        def perceive(self, prompt: str) -> Scene:
            raise RuntimeError("no detector configured")

    orchestrator = Orchestrator(
        PlannerAgentWrapper(RuleBasedPlanner()),
        ExecutionAgentWrapper(FakeSimulator(objects=_mug_table_scene())),
        memory_agent=_memory_agent(tmp_path),
        vision_agent=VisionAgentWrapper(_BrokenVisionAgent()),
    )

    task_state = orchestrator.run(SingleTask(goal="find", object="mug"))

    assert task_state.status == TaskStatus.SUCCEEDED

"""
test_agents_events.py

Purpose
-------
Unit tests for `agents.events`: `EventBus.publish()`/`get_events()`
per-task isolation and ordering.
"""

from __future__ import annotations

from agents.events import Event, EventBus, EventType


def test_events_are_scoped_per_task_and_ordered():
    bus = EventBus()
    bus.publish(Event(task_id="a", agent="orchestrator", event=EventType.TASK_CREATED))
    bus.publish(Event(task_id="a", agent="planner", event=EventType.PLAN_CREATED))
    bus.publish(Event(task_id="b", agent="orchestrator", event=EventType.TASK_CREATED))

    events_a = bus.get_events("a")
    assert [e.event for e in events_a] == [
        EventType.TASK_CREATED,
        EventType.PLAN_CREATED,
    ]
    assert len(bus.get_events("b")) == 1
    assert bus.get_events("missing") == []


def test_clear_removes_only_that_task():
    bus = EventBus()
    bus.publish(Event(task_id="a", agent="orchestrator", event=EventType.TASK_CREATED))
    bus.publish(Event(task_id="b", agent="orchestrator", event=EventType.TASK_CREATED))
    bus.clear("a")
    assert bus.get_events("a") == []
    assert len(bus.get_events("b")) == 1

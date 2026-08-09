"""
events.py (backend/agents)

Purpose
-------
The structured event system section 7.17 asks for: a closed
`EventType` vocabulary, an `Event` record, and `EventBus` -- an
in-memory, append-only, per-task event log `Orchestrator` publishes to
at every lifecycle transition. Designed to be the direct backing for a
future `GET /tasks/{id}/events` route and the Activity/Mission
Control/Mission Detail frontend pages (section 7.18) without those
pages needing translation: `Event` already carries every field section
7.18 lists (`task_id, agent, event, timestamp, ... latency`).

Why in-memory, not persisted, this session
------------------------------------------------
Persistence (surviving a process restart, backing a research
experiments log) is section 7.18's concern and this session's plan
explicitly defers it -- see the plan's "what is explicitly deferred"
section. `EventBus` is deliberately just a `Dict[str, List[Event]]`
so a persistence-backed implementation can be swapped in later behind
the exact same `publish()`/`get_events()` interface, without
`Orchestrator` (or any frontend consumer) changing.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class EventType(str, Enum):
    """Every event `Orchestrator` can publish -- section 7.17's list."""

    TASK_CREATED = "TASK_CREATED"
    TASK_PARSED = "TASK_PARSED"
    MEMORY_RETRIEVED = "MEMORY_RETRIEVED"
    PLAN_CREATED = "PLAN_CREATED"
    OBSERVATION_RECEIVED = "OBSERVATION_RECEIVED"
    ACTION_STARTED = "ACTION_STARTED"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    ACTION_FAILED = "ACTION_FAILED"
    REFLECTION_COMPLETED = "REFLECTION_COMPLETED"
    REPLAN_TRIGGERED = "REPLAN_TRIGGERED"
    MEMORY_UPDATED = "MEMORY_UPDATED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    TASK_CANCELLED = "TASK_CANCELLED"


class Event(BaseModel):
    """One structured event -- section 7.18's observability fields."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    agent: str
    event: EventType
    timestamp: float = Field(default_factory=time.time)
    payload: Dict[str, Any] = Field(default_factory=dict)
    latency_ms: Optional[float] = None


class EventBus:
    """
    Minimal in-memory event log, keyed by `task_id`. See module
    docstring for why persistence is deliberately out of scope here.
    """

    def __init__(self) -> None:
        self._events: Dict[str, List[Event]] = {}

    def publish(self, event: Event) -> None:
        self._events.setdefault(event.task_id, []).append(event)

    def get_events(self, task_id: str) -> List[Event]:
        return list(self._events.get(task_id, []))

    def clear(self, task_id: str) -> None:
        self._events.pop(task_id, None)

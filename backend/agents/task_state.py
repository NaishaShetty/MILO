"""
task_state.py (backend/agents)

Purpose
-------
`TaskState` -- the single, centralized, mutable record the
`Orchestrator` threads through every agent call for one task (section
7.4). Exists so the full lifecycle of one task (what was asked, what
was retrieved, what was planned, what happened, what failed, what got
replanned) is inspectable as one object -- the future `GET
/tasks/{id}/state` response is this object, serialized, with nothing
translated or re-derived.

Why a dataclass, not a Pydantic model
------------------------------------------
Every other schema in this project (`schemas/task.py`,
`execution/models.py`, `agents/contracts.py`) is Pydantic because it
crosses a validation boundary (LLM output, HTTP request body).
`TaskState` never does -- it is only ever constructed and mutated by
`Orchestrator` itself, in-process, from already-validated pieces
(`SingleTask`, `planner.models.Plan`, `execution.models.
ExecutionRecord`). A plain `dataclass` avoids re-validating already-
trusted data on every mutation; `to_dict()` below covers the one
place this *does* need to become JSON (an API response), matching
`execution.models.ExecutionRecord`'s own precedent of a dataclass/
Pydantic model exposing a serialization helper rather than forcing
every internal mutation through Pydantic's validation path.

One `TaskState` per task, not per agent
------------------------------------------------
Every agent's individual output (a `PlanningResult`, an
`ExecutionRecord`, a `PlannerMemoryContext`) already has its own typed
model, defined in its owning package. `TaskState` does not duplicate
those types field-by-field -- it *holds* them (`current_plan:
Optional[Plan]`, `execution_history: List[ExecutionRecord]`, ...) so
nothing about an agent's own output shape needs to change for this
file to exist, per this phase's "reuse, don't duplicate" rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from agents.contracts import AgentState
from agents.failures import AgentFailure
from execution.models import ExecutionRecord
from planner.models import Plan


class InputSource(str, Enum):
    """Where `user_request` came from -- section 7.14's text/speech split."""

    TEXT = "text"
    SPEECH = "speech"


class TaskStatus(str, Enum):
    """`TaskState.status` -- one value per stage of the section 7.16 lifecycle."""

    CREATED = "created"
    PARSING = "parsing"
    RETRIEVING_MEMORY = "retrieving_memory"
    PLANNING = "planning"
    EXECUTING = "executing"
    REFLECTING = "reflecting"
    REPLANNING = "replanning"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskState:
    """The centralized, mutable task record. See module docstring."""

    task_id: str
    user_request: str
    input_source: InputSource = InputSource.TEXT
    goal: Optional[str] = None
    objects: List[str] = field(default_factory=list)
    target: Optional[str] = None
    current_location: Optional[str] = None
    current_plan: Optional[Plan] = None
    current_step: Optional[int] = None
    observations: List[Dict[str, Any]] = field(default_factory=list)
    known_objects: List[str] = field(default_factory=list)
    completed_steps: List[int] = field(default_factory=list)
    execution_history: List[ExecutionRecord] = field(default_factory=list)
    failures: List[AgentFailure] = field(default_factory=list)
    retrieved_memories: List[Dict[str, Any]] = field(default_factory=list)
    agent_states: Dict[str, AgentState] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.CREATED
    #: Wall-clock time (ms) spent in each named stage
    #: (`memory_retrieval_ms, planning_ms, vision_ms, execution_ms,
    #: memory_write_ms, total_ms`) -- section 7.18's observability,
    #: populated by `Orchestrator` wrapping each stage in
    #: `time.perf_counter()`. Never invented -- a stage this task never
    #: reached (e.g. `vision_ms` when no `VisionAgentWrapper` was
    #: configured) simply has no key.
    latencies_ms: Dict[str, float] = field(default_factory=dict)
    #: Every memory `Orchestrator._remember_terminal()` successfully
    #: wrote for this task -- `{"memory_id": ..., "memory_type": ...}`.
    #: Distinct from `retrieved_memories` (memory read *before*
    #: planning); this is memory written *after* the task concluded.
    created_memories: List[Dict[str, Any]] = field(default_factory=list)

    def metrics(self) -> Dict[str, Any]:
        """
        Derived task metrics -- section 7.18's "make real metrics
        available," never invented: every number here is computed
        from fields this object already stores, nothing new is
        measured or estimated. `replans` counts attempts beyond the
        first (an attempt is one `ExecutionRecord` in
        `execution_history`); `actions` sums every step this task
        actually dispatched, across every attempt.
        """
        attempts = len(self.execution_history)
        return {
            "actions": sum(
                len(record.step_results) for record in self.execution_history
            ),
            "failures": len(self.failures),
            "replans": max(attempts - 1, 0),
            "attempts": attempts,
            "success": self.status == TaskStatus.SUCCEEDED,
            "total_ms": self.latencies_ms.get("total_ms"),
        }

    def to_dict(self) -> Dict[str, Any]:
        """
        JSON-serializable snapshot for an API response. Nested typed
        models (`Plan`, `ExecutionRecord`, `AgentFailure`) use their own
        `.model_dump(mode="json")` -- never hand-serialized here -- so
        this stays correct if any of those models grow a field later.
        """
        return {
            "task_id": self.task_id,
            "user_request": self.user_request,
            "input_source": self.input_source.value,
            "goal": self.goal,
            "objects": self.objects,
            "target": self.target,
            "current_location": self.current_location,
            "current_plan": (
                self.current_plan.model_dump(mode="json")
                if self.current_plan is not None
                else None
            ),
            "current_step": self.current_step,
            "observations": self.observations,
            "known_objects": self.known_objects,
            "completed_steps": self.completed_steps,
            "execution_history": [
                record.model_dump(mode="json") for record in self.execution_history
            ],
            "failures": [f.model_dump(mode="json") for f in self.failures],
            "retrieved_memories": self.retrieved_memories,
            "agent_states": {k: v.value for k, v in self.agent_states.items()},
            "status": self.status.value,
            "latencies_ms": self.latencies_ms,
            "created_memories": self.created_memories,
            "metrics": self.metrics(),
        }

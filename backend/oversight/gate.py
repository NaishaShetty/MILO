"""
gate.py (backend/oversight)

`ApprovalGate` -- where a running mission stops and waits for the user:

- before a **risky step** (a risky action, a fragile or dangerous object, anything in
  the constraints file): approve or skip, with a plain reason;
- before running a **plan MILO worked out itself** (novel tasks): approve, edit (leave
  steps out) or cancel.

The waiting request is put on the task (`task_state.pending_decision`) so the UI can show
it; `decide(task_id, ...)` answers from the API thread. With no answer within `timeout_s`
a step is skipped and a plan is cancelled -- MILO never does a risky thing by default.

    MILO_APPROVALS = 1 | 0     (default 1 in the API; 0 = never ask)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from novel.safety import Constraints

IRREVERSIBLE = {"push", "put_down"}


@dataclass
class Decision:
    choice: str  # "approve" | "skip" | "cancel"
    steps: Optional[List[Dict[str, Any]]] = None  # an edited plan, for "approve"


@dataclass
class _Waiting:
    event: threading.Event = field(default_factory=threading.Event)
    decision: Optional[Decision] = None


class ApprovalGate:
    def __init__(
        self, constraints: Optional[Constraints] = None, timeout_s: float = 300.0
    ) -> None:
        self.constraints = constraints or Constraints.load()
        self.timeout_s = timeout_s
        self._waiting: Dict[str, _Waiting] = {}
        self._lock = threading.Lock()

    # -- classification ----------------------------------------------------------------

    def step_risk(self, action: str, target: Optional[str]) -> Optional[str]:
        from oversight.ambiguity import display_name

        why = self.constraints.risk(action, display_name(target))
        if why and action in IRREVERSIBLE:
            why += " (I can't undo this)"
        return why

    # -- waiting -------------------------------------------------------------------------

    def ask(self, task_state: Any, request: Dict[str, Any]) -> Decision:
        """Blocks the mission thread until `decide()` or the timeout."""
        waiting = _Waiting()
        with self._lock:
            self._waiting[task_state.task_id] = waiting
        task_state.pending_decision = {**request, "asked_at": time.time()}
        try:
            answered = waiting.event.wait(self.timeout_s)
        finally:
            with self._lock:
                self._waiting.pop(task_state.task_id, None)
            task_state.pending_decision = None
        if not answered or waiting.decision is None:
            return Decision("skip" if request.get("kind") == "step" else "cancel")
        return waiting.decision

    def decide(self, task_id: str, decision: Decision) -> bool:
        with self._lock:
            waiting = self._waiting.get(task_id)
        if waiting is None:
            return False
        waiting.decision = decision
        waiting.event.set()
        return True

    def cancel_all(self, task_id: str) -> None:
        self.decide(task_id, Decision("cancel"))

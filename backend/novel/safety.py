"""
safety.py (backend/novel)

The constraints file (`config/novel_constraints.json`, or `MILO_NOVEL_CONSTRAINTS`) and
the budgets every novel task runs under. Nothing here executes anything: it classifies
steps as allowed / forbidden / risky so the validator and solver can stop and ask.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config" / "novel_constraints.json"


@dataclass
class Budgets:
    max_steps: int = 20
    max_model_calls: int = 4
    max_wall_s: float = 90.0
    max_probes: int = 3


@dataclass
class Constraints:
    allowed_actions: List[str] = field(default_factory=list)
    forbidden_actions: List[str] = field(default_factory=list)
    risky_actions: List[str] = field(default_factory=list)
    fragile_objects: List[str] = field(default_factory=list)
    dangerous_objects: List[str] = field(default_factory=list)
    forbidden_objects: List[str] = field(default_factory=list)
    budgets: Budgets = field(default_factory=Budgets)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Constraints":
        path = Path(path or os.environ.get("MILO_NOVEL_CONSTRAINTS") or DEFAULT_PATH)
        data: Dict[str, Any] = json.loads(path.read_text())
        lists = {
            k: [str(v).lower() for v in data.get(k, [])]
            for k in (
                "allowed_actions",
                "forbidden_actions",
                "risky_actions",
                "fragile_objects",
                "dangerous_objects",
                "forbidden_objects",
            )
        }
        return cls(**lists, budgets=Budgets(**(data.get("budgets") or {})))

    # -- classification --------------------------------------------------------

    @staticmethod
    def _norm(name: Optional[str]) -> str:
        return (name or "").replace(" ", "").replace("_", "").lower()

    def _in(self, name: Optional[str], names: Sequence[str]) -> bool:
        n = self._norm(name)
        return bool(n) and any(n == self._norm(x) for x in names)

    def forbidden(self, action: str, target: Optional[str]) -> Optional[str]:
        """A plain reason the step may never run, or None."""
        if self.allowed_actions and action not in self.allowed_actions:
            return f"I'm not allowed to '{action}'"
        if action in self.forbidden_actions:
            return f"I'm not allowed to '{action}'"
        if self._in(target, self.forbidden_objects):
            return f"I'm not allowed to touch the {target}"
        return None

    def risk(self, action: str, target: Optional[str]) -> Optional[str]:
        """Why the step needs the user's OK first, or None."""
        if action in ("locate", "navigate", "look_around"):
            return None
        if self._in(target, self.dangerous_objects):
            return f"the {target} could be dangerous"
        if action in self.risky_actions and self._in(target, self.fragile_objects):
            verb = {"put_down": "put it down", "push": "push it"}.get(
                action, action.replace("_", " ") + " it"
            )
            return f"the {target} is fragile and could break if I {verb}"
        if action in self.risky_actions:
            return f"'{action.replace('_', ' ')}' can't always be undone"
        return None

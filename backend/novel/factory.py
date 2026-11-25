"""
factory.py (backend/novel)

Builds a `NovelPlanner` wired to a live execution agent (scene metadata and safe
exploration probes), MILO's memory, the skill library and the orchestrator's failure
list.

    MILO_NOVEL_SOLVER = 1 | 0       route unknown commands to the novel planner (default 1)
    MILO_SKILLS_DB    = data/skills.db
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from execution.resolver import ObjectResolver
from novel.planner import NovelPlanner
from novel.providers import Provider, build_provider
from novel.safety import Constraints
from novel.skills import SkillLibrary
from planner.models import Plan, PlanStep

_resolver = ObjectResolver()
_WATCH = ("isOpen", "isToggled", "visible", "isPickedUp")


def enabled() -> bool:
    return os.environ.get("MILO_NOVEL_SOLVER", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _snapshot(meta: Dict[str, Any], name: str) -> Dict[str, Any]:
    oid = _resolver.resolve(name, meta)
    obj = next((o for o in meta.get("objects") or [] if o.get("objectId") == oid), None)
    return {k: obj.get(k) for k in _WATCH} if obj else {}


def make_probe(execution: Any) -> Callable[[str, str], Optional[Dict[str, Any]]]:
    """Runs `navigate target` + `action target` and returns what changed on the target
    (None if the probe failed)."""
    from planner.state import WorldState

    def probe(action: str, target: str) -> Optional[Dict[str, Any]]:
        before = _snapshot(execution.get_metadata() or {}, target)
        plan = Plan(
            task_id="probe",
            planner_type="novel",
            goal_summary={"goal": f"try to {action} the {target}"},
            steps=[
                PlanStep(
                    step_id=1, action="navigate", target=target, description="probe"
                ),
                PlanStep(step_id=2, action=action, target=target, description="probe"),
            ],
        )
        record = execution.execute_plan(plan, WorldState.initial())
        if record.status.value != "success":
            return None
        after = _snapshot(execution.get_metadata() or {}, target)
        return {k: after[k] for k in after if after.get(k) != before.get(k)}

    return probe


_LIBRARIES: Dict[str, SkillLibrary] = {}


def shared_library(memory_agent: Any = None) -> SkillLibrary:
    path = os.environ.get("MILO_SKILLS_DB", "data/skills.db")
    if path not in _LIBRARIES:
        _LIBRARIES[path] = SkillLibrary(Path(path), memory_agent)
    return _LIBRARIES[path]


def build_novel_planner(
    execution: Any,
    *,
    memory_agent: Any = None,
    failure_source: Optional[Callable[[], List[str]]] = None,
    provider: Optional[Provider] = None,
    skills: Optional[SkillLibrary] = None,
    confirm: Any = None,
) -> NovelPlanner:
    def memories(command: str) -> List[str]:
        if memory_agent is None:
            return []
        try:
            return [m.content for m in memory_agent.list_memories(limit=8)]
        except Exception:
            return []

    return NovelPlanner(
        provider or build_provider(),
        execution.get_metadata,
        constraints=Constraints.load(),
        skills=skills or shared_library(memory_agent),
        memory_source=memories,
        failure_source=failure_source,
        probe=make_probe(execution),
        confirm=confirm,
    )

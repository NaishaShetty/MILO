"""
skills.py (backend/novel)

What MILO learns from novel tasks:

- **Skills**: a plan that worked, stored with the objects replaced by placeholders
  (`{o0}`, `{o1}`...), its success conditions, the wording that triggered it, and
  success/failure counts. A skill starts as a *candidate* and becomes *trusted* after
  `PROMOTE_AFTER` successes on at least two different object sets.
- **Lessons**: one line per failed attempt (what was tried, why it failed), shown to the
  planner next time a similar command comes in.

A command matches a skill when it has the same wording once object names are replaced
by placeholders ("chill the apple" and "chill the tomato" -> "chill the {o0}"). Stored in
SQLite (`MILO_SKILLS_DB`, default `data/skills.db`) and mirrored into MILO's memory when
a memory agent is available, so memory search can surface them too.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from novel.plan import NovelStep, Proposal
from verification.predicates import Predicate

PROMOTE_AFTER = 3
#: How deep skills may call skills ("tidy up" -> "put away X" -> ...).
MAX_DEPTH = 3
SKILL_PREFIX = "skill:"


class SkillChainError(ValueError):
    """A skill calls an unknown skill, calls itself (a cycle), or nests too deeply."""


def skill_id(template: str) -> str:
    import hashlib

    return hashlib.sha1(template.encode()).hexdigest()[:10]


_SQL = """
CREATE TABLE IF NOT EXISTS skills (
    template TEXT PRIMARY KEY, name TEXT, steps TEXT, success TEXT, status TEXT,
    successes INTEGER, failures INTEGER, object_sets TEXT, created_at REAL, last_used REAL
);
CREATE TABLE IF NOT EXISTS lessons (template TEXT, text TEXT, created_at REAL);
"""


def templatize(command: str, objects: Sequence[str]) -> Tuple[str, List[str]]:
    """Replace object names (longest first) by placeholders; returns (template, bound)."""
    text = re.sub(r"\s+", " ", command.lower().strip().rstrip(".!?"))
    bound: List[str] = []
    for name in sorted({o.lower() for o in objects if o}, key=len, reverse=True):
        pattern = rf"\b{re.escape(name)}s?\b"
        if re.search(pattern, text):
            text = re.sub(pattern, f"{{o{len(bound)}}}", text)
            bound.append(name)
    # renumber in order of appearance so "x then y" and "y then x" don't collide
    order = [int(i) for i in re.findall(r"\{o(\d+)\}", text)]
    remap = {old: new for new, old in enumerate(dict.fromkeys(order))}
    text = re.sub(r"\{o(\d+)\}", lambda m: f"{{o{remap[int(m.group(1))]}}}", text)
    bound = [bound[old] for old in dict.fromkeys(order)]
    return text, bound


def _abstract(value: Optional[str], bound: List[str]) -> Optional[str]:
    if value is None:
        return None
    return f"{{o{bound.index(value)}}}" if value in bound else value


def _concrete(value: Optional[str], binding: List[str]) -> Optional[str]:
    if value is None:
        return None
    m = re.fullmatch(r"\{o(\d+)\}", value)
    return binding[int(m.group(1))] if m else value


@dataclass
class Skill:
    template: str
    name: str
    steps: List[Dict[str, Any]]
    success: List[Dict[str, Any]]
    status: str = "candidate"
    successes: int = 0
    failures: int = 0
    object_sets: List[List[str]] = field(default_factory=list)
    last_used: Optional[float] = None

    @property
    def skill_id(self) -> str:
        return skill_id(self.template)

    def instantiate(
        self,
        binding: List[str],
        library: Optional["SkillLibrary"] = None,
        _depth: int = 0,
        _seen: Optional[List[str]] = None,
    ) -> Proposal:
        """Concrete steps for `binding`. A step `{"action": "skill:<name>", "target": a,
        "container": b}` calls another skill with (a, b) as its objects and is expanded
        in place -- at most `MAX_DEPTH` deep, never into a skill already on the stack.
        """
        seen = (_seen or []) + [self.template]
        if _depth > MAX_DEPTH:
            raise SkillChainError(
                f"'{self.name}' calls skills more than {MAX_DEPTH} levels deep"
            )
        steps: List[NovelStep] = []
        for s in self.steps:
            target = _concrete(s.get("target"), binding)
            container = _concrete(s.get("container"), binding)
            action = str(s["action"])
            if not action.startswith(SKILL_PREFIX):
                steps.append(NovelStep(action, target, container))
                continue
            name = action[len(SKILL_PREFIX) :]
            inner = library.by_name(name) if library is not None else None
            if inner is None:
                raise SkillChainError(
                    f"'{self.name}' uses a skill I don't know: '{name}'"
                )
            if inner.template in seen:
                raise SkillChainError(
                    f"'{self.name}' and '{inner.name}' call each other in a loop"
                )
            args = [a for a in (target, container) if a]
            steps.extend(inner.instantiate(args, library, _depth + 1, seen).steps)
        success = [
            Predicate(
                p["kind"],
                _concrete(p.get("object"), binding),
                _concrete(p.get("receptacle"), binding),
            )
            for p in self.success
        ]
        return Proposal(goal=self.name, success=success, steps=steps)

    def to_dict(self) -> Dict[str, Any]:
        runs = self.successes + self.failures
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "wording": self.template,
            "status": self.status,
            "successes": self.successes,
            "failures": self.failures,
            "success_rate": (self.successes / runs) if runs else None,
            "last_used": self.last_used,
            "steps": self.steps,
            "success": self.success,
            "objects_seen": self.object_sets,
        }

    def describe(self) -> str:
        return (
            f"{SKILL_PREFIX}{self.name} [{self.status}, {self.successes} ok / {self.failures} failed]: "
            + ", ".join(
                f"{s['action']} {s.get('target') or ''}".strip() for s in self.steps
            )
        )


class SkillLibrary:
    def __init__(self, path: Path, memory_agent: Any = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._memory = memory_agent
        self._lock = threading.Lock()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript(_SQL)

    def _db(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5.0)

    # -- skills ------------------------------------------------------------------------

    def find(
        self, command: str, scene_objects: Sequence[str]
    ) -> Optional[Tuple[Skill, List[str]]]:
        template, binding = templatize(command, scene_objects)
        skill = self.get(template)
        if skill is None or skill.status == "disabled":
            return None
        return skill, binding

    def by_id(self, sid: str) -> Optional[Skill]:
        return next((s for s in self.all() if s.skill_id == sid), None)

    def by_name(self, name: str) -> Optional[Skill]:
        name = name.strip().lower()
        return next(
            (
                s
                for s in self.all()
                if s.status != "disabled" and name in (s.name.lower(), s.template)
            ),
            None,
        )

    def expand(self, proposal: Proposal) -> Proposal:
        """Replaces `skill:<name>` steps in a proposal (e.g. from the planner) by the
        named skill's steps; raises `SkillChainError` if one can't be expanded."""
        if not any(s.action.startswith(SKILL_PREFIX) for s in proposal.steps):
            return proposal
        wrapper = Skill(
            template="(plan)",
            name=proposal.goal or "plan",
            steps=[s.to_dict() for s in proposal.steps],
            success=[],
        )
        steps = wrapper.instantiate([], self).steps
        return Proposal(proposal.goal, proposal.success, steps)

    def save(
        self,
        name: str,
        wording: str,
        proposal: Proposal,
        scene_objects: Sequence[str],
        *,
        status: str = "candidate",
    ) -> Skill:
        """Stores a skill from explicit wording ("set the mug on the table") and a plan
        that worked; objects named in the wording become placeholders everywhere."""
        template, bound = templatize(wording, scene_objects)
        skill = Skill(
            template=template,
            name=name.strip() or wording,
            steps=[
                {
                    "action": s.action,
                    "target": _abstract(s.target, bound),
                    "container": _abstract(s.container, bound),
                }
                for s in proposal.steps
            ],
            success=[
                {
                    "kind": p.kind,
                    "object": _abstract(p.object, bound),
                    "receptacle": _abstract(p.receptacle, bound),
                }
                for p in proposal.success
            ],
            status=status,
            successes=1,
            object_sets=[bound],
            last_used=time.time(),
        )
        self.check_chain(skill)
        with self._lock:
            self._save(skill)
        self._mirror(f"skill: {skill.describe()}", "skill")
        return skill

    def check_chain(self, skill: Skill) -> None:
        """Dry-run expansion with placeholder objects (catches cycles/unknown skills)."""
        n = 1 + max(
            [
                int(m)
                for s in skill.steps
                for v in (s.get("target"), s.get("container"))
                for m in re.findall(r"\{o(\d+)\}", v or "")
            ]
            or [0]
        )
        skill.instantiate([f"thing{i}" for i in range(n)], self)

    def rename(self, sid: str, name: str) -> Optional[Skill]:
        skill = self.by_id(sid)
        if skill is None:
            return None
        skill.name = name.strip() or skill.name
        self._save(skill)
        return skill

    def update_steps(self, sid: str, steps: List[Dict[str, Any]]) -> Optional[Skill]:
        skill = self.by_id(sid)
        if skill is None:
            return None
        skill.steps = [
            {
                "action": str(s["action"]).strip().lower(),
                "target": s.get("target") or None,
                "container": s.get("container") or None,
            }
            for s in steps
        ]
        self.check_chain(skill)
        self._save(skill)
        return skill

    def delete(self, sid: str) -> bool:
        skill = self.by_id(sid)
        if skill is None:
            return False
        with closing(self._db()) as db, db:
            db.execute("DELETE FROM skills WHERE template=?", (skill.template,))
        return True

    def get(self, template: str) -> Optional[Skill]:
        with closing(self._db()) as db:
            row = db.execute(
                "SELECT * FROM skills WHERE template=?", (template,)
            ).fetchone()
        return self._row(row) if row else None

    def all(self) -> List[Skill]:
        with closing(self._db()) as db:
            rows = db.execute("SELECT * FROM skills ORDER BY last_used DESC").fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(row: Tuple) -> Skill:
        return Skill(
            template=row[0],
            name=row[1],
            steps=json.loads(row[2]),
            success=json.loads(row[3]),
            status=row[4],
            successes=row[5],
            failures=row[6],
            object_sets=json.loads(row[7]),
            last_used=row[9],
        )

    def record_success(
        self, command: str, scene_objects: Sequence[str], proposal: Proposal
    ) -> Skill:
        template, bound = templatize(command, scene_objects)
        with self._lock:
            skill = self.get(template) or Skill(
                template=template,
                name=proposal.goal or command,
                steps=[
                    {
                        "action": s.action,
                        "target": _abstract(s.target, bound),
                        "container": _abstract(s.container, bound),
                    }
                    for s in proposal.steps
                ],
                success=[
                    {
                        "kind": p.kind,
                        "object": _abstract(p.object, bound),
                        "receptacle": _abstract(p.receptacle, bound),
                    }
                    for p in proposal.success
                ],
            )
            skill.successes += 1
            if skill.status == "teaching":
                skill.status = "candidate"  # the run-back worked: it's a real skill now
            if bound not in skill.object_sets:
                skill.object_sets.append(bound)
            if (
                skill.status == "candidate"
                and skill.successes >= PROMOTE_AFTER
                and len(skill.object_sets) >= 2
            ):
                skill.status = "trusted"
            skill.last_used = time.time()
            self._save(skill)
        self._mirror(f"skill: {skill.describe()}", "skill")
        return skill

    def record_failure(self, command: str, scene_objects: Sequence[str]) -> None:
        template, _ = templatize(command, scene_objects)
        with self._lock:
            skill = self.get(template)
            if skill is not None:
                skill.failures += 1
                skill.last_used = time.time()
                self._save(skill)

    def set_status(self, template: str, status: str) -> bool:
        skill = self.get(template)
        if skill is None:
            return False
        skill.status = status
        self._save(skill)
        return True

    def _save(self, s: Skill) -> None:
        with closing(self._db()) as db, db:
            db.execute(
                "INSERT OR REPLACE INTO skills VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    s.template,
                    s.name,
                    json.dumps(s.steps),
                    json.dumps(s.success),
                    s.status,
                    s.successes,
                    s.failures,
                    json.dumps(s.object_sets),
                    time.time(),
                    s.last_used,
                ),
            )

    # -- lessons -----------------------------------------------------------------------

    def add_lesson(self, command: str, scene_objects: Sequence[str], text: str) -> None:
        template, _ = templatize(command, scene_objects)
        with closing(self._db()) as db, db:
            db.execute(
                "INSERT INTO lessons VALUES (?,?,?)", (template, text, time.time())
            )
        self._mirror(f"lesson: {text}", "lesson")

    def lessons(
        self, command: str, scene_objects: Sequence[str], limit: int = 5
    ) -> List[str]:
        template, _ = templatize(command, scene_objects)
        with closing(self._db()) as db:
            rows = db.execute(
                "SELECT text FROM lessons WHERE template=? ORDER BY created_at DESC LIMIT ?",
                (template, limit),
            ).fetchall()
        return [r[0] for r in rows]

    # -- memory mirror -------------------------------------------------------------------

    def _mirror(self, text: str, kind: str) -> None:
        if self._memory is None:
            return
        try:
            from memory.models import MemoryProvenance

            self._memory.remember_observation(
                kind,
                "learned",
                text[:300],
                provenance=MemoryProvenance.EXECUTION,
                confidence=0.7,
            )
        except Exception:
            pass

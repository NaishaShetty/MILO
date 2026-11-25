"""
task_library.py (backend/planner)

Purpose
-------
The catalogue of everyday jobs MILO knows how to do -- one entry per
*kind* of request, with plain-language titles and example phrasings. It is
the single source of truth for three things:

- the "What can MILO do?" list in the UI (`GET /api/v1/tasks/library`);
- the help text MILO answers with when asked what it can do, and the
  "here is what I can do" part of an unsupported-request reply;
- the tests that make sure every advertised kind really is plannable by
  every planner (`tests/test_task_library.py`).

Entries carry no planning logic. How a kind is planned lives in the
planners' goal tables (`rule_based.GOAL_HANDLERS`, `htn.HTN_GOAL_TASKS`);
how a *sentence* becomes one of these goals lives in
`language/interpreter.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


@dataclass(frozen=True)
class TaskKind:
    """One kind of job MILO can do."""

    id: str
    title: str
    summary: str
    examples: Tuple[str, ...]
    #: Canonical goal name(s) the planners receive for this kind.
    goals: Tuple[str, ...]
    #: True for kinds that expand into several sub-goals at run time.
    composite: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "examples": list(self.examples),
            "goals": list(self.goals),
            "composite": self.composite,
        }


TASK_LIBRARY: List[TaskKind] = [
    TaskKind(
        id="fetch",
        title="Fetch something",
        summary="Go to it, pick it up and bring it back to you.",
        examples=("Bring me the mug", "Could you grab me the apple?"),
        goals=("fetch",),
    ),
    TaskKind(
        id="deliver",
        title="Take something somewhere",
        summary="Pick something up and carry it to another place.",
        examples=("Take the book to the desk", "Bring the apple to the table"),
        goals=("deliver",),
    ),
    TaskKind(
        id="put",
        title="Put something in or on something",
        summary="Pick it up and put it inside a container or on a surface.",
        examples=("Put the apple in the fridge", "Put the mug on the shelf"),
        goals=("store", "place"),
    ),
    TaskKind(
        id="open_close",
        title="Open or close something",
        summary="Walk up to a door, drawer or fridge and open or close it.",
        examples=("Open the drawer", "Close the fridge"),
        goals=("open", "close"),
    ),
    TaskKind(
        id="toggle",
        title="Turn something on or off",
        summary="Switch lights, the tap, the toaster and other things on or off.",
        examples=("Turn on the lights", "Switch off the tap"),
        goals=("turn_on", "turn_off"),
    ),
    TaskKind(
        id="find",
        title="Find something",
        summary="Look around for it and tell you where it is.",
        examples=("Find the mug", "Where is the book?"),
        goals=("find",),
    ),
    TaskKind(
        id="clear_table",
        title="Clear a table",
        summary="Move everything off a table or counter to a place you choose.",
        examples=("Clear the table onto the counter",),
        goals=("clear_table",),
        composite=True,
    ),
    TaskKind(
        id="tidy_up",
        title="Tidy up",
        summary="Put every out-of-place thing back where it usually lives.",
        examples=("Tidy up", "Put everything away"),
        goals=("tidy_up",),
        composite=True,
    ),
    TaskKind(
        id="answer",
        title="Answer a question",
        summary="Tell you what MILO can see, hold or remember, without moving.",
        examples=("Is the fridge open?", "What are you holding?"),
        goals=(),
    ),
]

#: Goals that expand into several sub-goals once the room is known.
COMPOSITE_GOALS = frozenset(k.goals[0] for k in TASK_LIBRARY if k.composite)


def library_as_dicts() -> List[Dict[str, Any]]:
    return [kind.to_dict() for kind in TASK_LIBRARY]


def capabilities_sentence() -> str:
    """A short plain-language answer to "what can you do?"."""
    parts = [kind.title.lower() for kind in TASK_LIBRARY if kind.goals]
    return "I can " + ", ".join(parts[:-1]) + ", and " + parts[-1] + "."

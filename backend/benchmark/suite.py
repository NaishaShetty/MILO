"""
suite.py (backend/benchmark)

The fixed benchmark: one synthetic home (the novel-task benchmark's), fixed tasks,
fixed fault settings, fixed seeds -- so results are reproducible run to run.

- **known** tasks: 24 task-library missions (fetch, place, store, open, close, switch
  on/off, find) over different objects;
- **novel** tasks: 8 commands with no recipe, run by the language-model planner (the
  `novel` planner). In CI and offline it uses the reference plans of
  `novel.eval_novel` (an upper bound for the pipeline, not an LLM result); with
  `--provider claude` and credentials, the real model.
- **faults**: every known task again under each injected fault kind, recoverable
  (the fault happens once or twice, then clears), to measure recovery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

FAULT_KINDS = [
    "blocked_path",
    "out_of_reach",
    "door_stuck",
    "timeout",
    "wrong_detection",
    "missing_object",
]


@dataclass(frozen=True)
class Case:
    case_id: str
    kind: str  # "known" | "novel"
    goal: str
    object: Optional[str] = None
    target: Optional[str] = None
    command: Optional[str] = None  # for novel cases
    fault: str = "none"
    fault_target: Optional[str] = None
    fault_times: int = 1
    tags: List[str] = field(default_factory=list)

    def task_fields(self) -> Dict[str, Any]:
        if self.kind == "novel":
            return {"goal": "novel", "estimated_goal": self.command}
        return {
            k: v
            for k, v in {
                "goal": self.goal,
                "object": self.object,
                "target": self.target,
            }.items()
            if v
        }


KNOWN = [
    ("fetch", "apple", None), ("fetch", "mug", None), ("fetch", "book", None), ("fetch", "cup", None),
    ("place", "mug", "shelf"), ("place", "book", "sofa"), ("place", "bowl", "table"), ("place", "potato", "countertop"),
    ("store", "apple", "fridge"), ("store", "egg", "fridge"), ("store", "cup", "cabinet"), ("store", "book", "drawer"),
    ("open", "fridge", None), ("open", "drawer", None), ("open", "cabinet", None), ("close", "fridge", None),
    ("turn_on", "television", None), ("turn_on", "faucet", None), ("turn_off", "lightswitch", None), ("turn_on", "lightswitch", None),
    ("find", "tomato", None), ("find", "bottle", None), ("find", "plate", None), ("find", "egg", None),
]  # fmt: skip
NOVEL = [
    "chill the apple", "hide the book in the drawer", "shelve the bottle", "make the room dark",
    "get the telly going", "air out the fridge", "park the mug on the sofa", "take a look around the room",
]  # fmt: skip


def _fault_target(
    goal: str, obj: Optional[str], target: Optional[str]
) -> Optional[str]:
    if goal == "close":
        return obj
    return obj


def known_cases() -> List[Case]:
    out = []
    for goal, obj, target in KNOWN:
        if goal == "close":
            continue  # "close the fridge" needs it open first: covered by the novel/door cases
        out.append(
            Case(
                f"{goal}-{obj}" + (f"-{target}" if target else ""),
                "known",
                goal,
                obj,
                target,
            )
        )
    return out


def novel_cases() -> List[Case]:
    return [
        Case("novel-" + c.replace(" ", "-"), "novel", "novel", command=c) for c in NOVEL
    ]


def fault_cases(times: int = 1) -> List[Case]:
    out = []
    for c in known_cases():
        for fault in FAULT_KINDS:
            if fault == "door_stuck" and c.goal not in ("open", "store"):
                continue  # only matters when something gets opened
            target = (
                c.target
                if (fault == "door_stuck" and c.goal == "store")
                else _fault_target(c.goal, c.object, c.target)
            )
            out.append(
                Case(f"{c.case_id}+{fault}", "known", c.goal, c.object, c.target,
                     fault=fault, fault_target=target, fault_times=times, tags=["fault"])  # fmt: skip
            )
    return out


def full_suite() -> List[Case]:
    return known_cases() + novel_cases()


def ci_subset() -> List[Case]:
    """The fast slice run on every push: every 2nd known case, 4 novel cases, and one
    fault of each kind."""
    faults = fault_cases()
    seen, picked = set(), []
    for c in faults:
        if c.fault not in seen:
            seen.add(c.fault)
            picked.append(c)
    return known_cases()[::2] + novel_cases()[:4] + picked

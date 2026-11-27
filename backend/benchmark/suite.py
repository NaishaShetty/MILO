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
from typing import Any, Dict, List, Optional, Tuple

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
    #: Harder tiers: objects that start out of view, an ordered list of goals for one
    #: mission, and a scene variant (an extra, farther receptacle of the same type).
    hidden: Tuple[str, ...] = ()
    #: (object, other name): MILO remembers where the object is only under the other
    #: name ("ceramic mug" for "mug"), so finding it needs similarity, not exact lookup.
    aliases: Tuple[Tuple[str, str], ...] = ()
    subtasks: Tuple[Tuple[str, Optional[str], Optional[str]], ...] = ()
    variant: str = ""

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


def memory_cases() -> List[Case]:
    """The object starts out of view: it can't be walked to directly and looking around
    doesn't reveal it. Only going to where it usually is (memory) finds it."""
    tasks = [("fetch", "mug", None), ("fetch", "book", None), ("fetch", "bottle", None),
             ("place", "cup", "sofa"), ("place", "plate", "countertop"),
             ("store", "tomato", "fridge"), ("store", "potato", "cabinet"), ("store", "egg", "drawer")]  # fmt: skip
    return [Case(f"memory-{g}-{o}" + (f"-{t}" if t else ""), "memory", g, o, t, hidden=(o,))
            for g, o, t in tasks]  # fmt: skip


def long_cases() -> List[Case]:
    """Several goals in one mission, in the stated order (10 to 20 steps)."""
    chains = [
        (("store", "apple", "fridge"), ("turn_off", "lightswitch", None), ("fetch", "mug", None)),
        (("store", "book", "drawer"), ("turn_on", "television", None)),
        (("place", "bowl", "shelf"), ("place", "cup", "sofa"), ("turn_on", "faucet", None)),
        (("store", "egg", "fridge"), ("store", "cup", "cabinet")),
        (("open", "cabinet", None), ("place", "plate", "countertop"), ("fetch", "bottle", None)),
        (("turn_on", "television", None), ("store", "potato", "fridge"), ("place", "book", "sofa")),
    ]  # fmt: skip
    return [Case("long-" + "+".join(f"{g}-{o}" for g, o, _ in chain), "long", "multi", subtasks=chain)
            for chain in chains]  # fmt: skip


def route_cases() -> List[Case]:
    """Competing routes: the nearest shelf/table is blocked for good; a second one, further
    away, is clear. Success needs a planner that tries the other one."""
    tasks = [("place", "mug", "shelf", "Shelf"), ("place", "bowl", "shelf", "Shelf"),
             ("place", "book", "table", "Table"), ("place", "cup", "table", "Table")]  # fmt: skip
    return [Case(f"route-{g}-{o}-{t}", "routes", g, o, t, fault="blocked_path",
                 fault_target=f"{kind}|1", fault_times=99, variant=f"second_{t}")
            for g, o, t, kind in tasks]  # fmt: skip


#: Held-out paraphrases: none of these were used to choose the similarity threshold
#: (that probe used "coffee mug", "paperback", "water bottle", "dinner plate", "teacup",
#: "cherry tomato", "spud", "hen's egg").
SYNONYMS = {"mug": "ceramic mug", "book": "hardcover", "bottle": "flask", "cup": "paper cup",
            "plate": "serving plate", "tomato": "plum tomato", "potato": "baked potato",
            "egg": "boiled egg"}  # fmt: skip


def memory_synonym_cases() -> List[Case]:
    """The memory tier again, but each object's place is remembered only under another
    name: the memory embedder decides whether MILO finds it."""
    return [Case(c.case_id.replace("memory-", "memsyn-"), "memory_synonyms", c.goal, c.object, c.target,
                 hidden=c.hidden, aliases=((c.object or "", SYNONYMS[c.object or ""]),))
            for c in memory_cases()]  # fmt: skip


def impossible_cases() -> List[Case]:
    """Requests nothing in the home can carry out: a thing that can't be picked up,
    opened or switched on, a place that isn't a receptacle, an object that isn't there.
    Correct means MILO doesn't report success AND takes no action at all (not even
    walking over): refusing up front, not failing halfway.

    Ambiguous requests ("bring the cup" with two cups) are not a tier here: MILO asks
    its question in the API before a mission starts, and the benchmark runs missions
    from structured tasks. They are measured in the novel-task evaluation instead."""
    tasks = [("pick_up", "fridge", None), ("open", "apple", None), ("turn_on", "book", None),
             ("place", "sofa", "table"), ("fetch", "unicorn", None), ("store", "mug", "apple")]  # fmt: skip
    return [
        Case(f"impossible-{g}-{o}" + (f"-{t}" if t else ""), "impossible", g, o, t)
        for g, o, t in tasks
    ]


HARD_TIERS = ("memory", "memory_synonyms", "long", "routes", "impossible")


def hard_cases() -> List[Case]:
    return (
        memory_cases()
        + memory_synonym_cases()
        + long_cases()
        + route_cases()
        + impossible_cases()
    )


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

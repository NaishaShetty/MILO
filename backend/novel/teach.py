"""
teach.py (backend/novel)

Turning what the user shows or tells MILO into skills:

- `proposal_from_words(lines, metadata)` -- "Teach MILO" mode: each line is an
  ordinary instruction ("pick up the mug", "put it on the table"); "it"/"them"/"that"
  mean the last thing mentioned. Lines are understood by MILO's own phrasebook and
  planned by the rule-based planner against the current scene, one after the other.
- `proposal_from_task(task_state)` -- "Save as skill": the steps of a mission that
  succeeded, with the success conditions that were checked at the end.

Either result is saved with `SkillLibrary.save(...)` using the wording the user wants to
trigger it with ("set the {mug} on the table" -> "set the {o0} on the table").
"""

from __future__ import annotations

import re
from typing import Any, List, Mapping, Optional, Tuple

from language.interpreter import InstructionInterpreter
from novel.plan import NovelStep, Proposal
from novel.validate import seed_state
from planner.factory import create_planner
from schemas.task import SingleTask
from verification.predicates import Predicate, goal_predicates

_PRONOUN = re.compile(r"\b(it|them|that|this one)\b")


class TeachError(ValueError):
    """A taught step MILO could not understand or plan; the message says which."""


def _objects_of(task: SingleTask) -> List[str]:
    return [o for o in (task.object, task.target, task.target_location) if o]


def proposal_from_words(
    lines: List[str], metadata: Optional[Mapping[str, Any]], goal: str = ""
) -> Proposal:
    interpreter = InstructionInterpreter()
    tasks: List[SingleTask] = []
    last: Optional[str] = None
    for n, raw in enumerate([ln.strip() for ln in lines if ln.strip()], start=1):
        text = _PRONOUN.sub(f"the {last}", raw.lower()) if last else raw
        result = interpreter.interpret(text)
        if result.kind != "task" or not isinstance(result.task, SingleTask):
            raise TeachError(
                f'I didn\'t understand step {n}: "{raw}". {result.message}'.strip()
            )
        tasks.append(result.task)
        last = result.task.object or last
    if not tasks:
        raise TeachError("Tell me at least one step.")
    planner = create_planner("rule_based")
    planned = planner.plan_multi(tasks, seed_state(metadata), None)
    if not planned.success or planned.plan is None:
        reason = "; ".join(planned.errors) or "those steps don't fit together here"
        raise TeachError(f"I can't do those steps in this room: {reason}.")
    steps = [
        NovelStep(s.action, s.target, s.parameters.get("container"))
        for s in planned.plan.steps
    ]
    # Success = the end state: a step's condition is dropped when a later step acts on
    # the same thing ("pick up the mug" is not still true after "put it on the table").
    success: List[Predicate] = []
    for i, t in enumerate(tasks):
        later = {o for u in tasks[i + 1 :] for o in _objects_of(u)}
        later_hands = any(
            u.goal in ("pick_up", "fetch", "place", "store") for u in tasks[i + 1 :]
        )
        for p in goal_predicates(t):
            if p.object in later or (p.kind == "hand_empty" and later_hands):
                continue
            success.append(p)
    return Proposal(goal=goal, success=success, steps=steps)


def proposal_from_task(task_state: Any) -> Tuple[Proposal, List[str]]:
    """(proposal, objects used) from a succeeded mission's final plan."""
    plan = task_state.current_plan
    if task_state.status.value != "succeeded" or plan is None or not plan.steps:
        raise TeachError("I can only save a mission that finished successfully.")
    steps = [
        NovelStep(s.action, s.target, (s.parameters or {}).get("container"))
        for s in plan.steps
    ]
    success = [
        Predicate.from_dict(v)
        for v in (task_state.verification or [])
        if v.get("ok") and v.get("kind")
    ]
    objects = sorted(
        {x for s in steps for x in (s.target, s.container) if x}
        | {x for p in success for x in (p.object, p.receptacle) if x}
    )
    return Proposal(goal=task_state.user_request, success=success, steps=steps), objects


_ = _objects_of

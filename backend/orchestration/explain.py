"""
explain.py (backend/orchestration)

Purpose
-------
Plain-language sentences for what MILO is doing and why -- the words in
MILO's speech bubble and the "MILO's thoughts" feed. Everything here is a
pure function of data the system already has (a plan step, its status, a
failure category, a reflection verdict); there is no model call and no
invention: an explanation only ever restates what actually happened.

Three kinds of sentence:

- `explain_step(step, phase)`   -- "Walking to the apple." while a step
  runs, "Got the apple." once it is done;
- `explain_verdict(...)`        -- what a reflection verdict *means* for
  the user: `continue` ("All done!"), `retry` ("That didn't work, so I'm
  trying it again."), `replan` ("I couldn't reach the fridge, so I'm
  trying another route."), `abort` ("I had to stop: ...");
- `explain_plan(...)`           -- "Plan ready: 8 small steps ...".

Jargon stays out: no "precondition", "replan" or "perception".
"""

from __future__ import annotations

from typing import Optional

from agents.failures import AgentFailure, FailureCategory
from planner.models import PlanStep


def _the(name: Optional[str]) -> str:
    return f"the {name}" if name else "it"


def explain_step(step: PlanStep, phase: str) -> str:
    """`phase` is `"doing"` (about to run / running) or `"done"`."""
    t = step.target
    container = step.parameters.get("container")
    doing = {
        "locate": f"Looking for {_the(t)}.",
        "navigate": f"Walking to {_the(t)}.",
        "pickup": f"Picking up {_the(t)}.",
        "place": f"Putting {_the(t)} in {_the(container)}.",
        "open": f"Opening {_the(t)}.",
        "close": f"Closing {_the(t)}.",
        "turn_on": f"Turning on {_the(t)}.",
        "turn_off": f"Turning off {_the(t)}.",
        "put_down": f"Putting down {_the(t)}.",
        "act": f"Working on {_the(t)}.",
    }
    done = {
        "locate": f"I can see {_the(t)}.",
        "navigate": (
            "I'm back with you."
            if (t or "").lower() in ("user", "me", "home")
            else f"I'm next to {_the(t)}."
        ),
        "pickup": f"Got {_the(t)}.",
        "place": f"{_the(t).capitalize()} is in {_the(container)}.",
        "open": f"{_the(t).capitalize()} is open.",
        "close": f"{_the(t).capitalize()} is closed.",
        "turn_on": f"{_the(t).capitalize()} is on.",
        "turn_off": f"{_the(t).capitalize()} is off.",
        "put_down": f"Put {_the(t)} down.",
        "act": f"Finished with {_the(t)}.",
    }
    table = done if phase == "done" else doing
    return table.get(step.action, step.description or "Working on it.")


def _friendly_reason(failure: Optional[AgentFailure]) -> str:
    if failure is None:
        return "something went wrong"
    return {
        FailureCategory.PATH_BLOCKED: "something was in the way",
        FailureCategory.NAVIGATION_FAILURE: "I couldn't get there",
        FailureCategory.OBJECT_NOT_FOUND: "I couldn't find it",
        FailureCategory.OBJECT_NOT_VISIBLE: "I couldn't see it",
        FailureCategory.TIMEOUT: "it took too long",
        FailureCategory.INVALID_PLAN: "the plan didn't make sense",
        FailureCategory.INVALID_ACTION: "that isn't something I can do",
    }.get(failure.category, "that didn't work")


def explain_verdict(
    verdict: str,
    failed_step: Optional[PlanStep] = None,
    failure: Optional[AgentFailure] = None,
) -> str:
    """One sentence for a reflection verdict, naming the thing that failed."""
    target = failed_step.target if failed_step is not None else None
    if verdict == "continue":
        return "All done!"
    if verdict == "retry":
        return "That didn't quite work, so I'm trying it again."
    if verdict == "replan":
        category = failure.category if failure is not None else None
        if category in (
            FailureCategory.NAVIGATION_FAILURE,
            FailureCategory.PATH_BLOCKED,
        ):
            return f"I couldn't reach {_the(target)}, so I'm trying another route."
        if category in (
            FailureCategory.OBJECT_NOT_FOUND,
            FailureCategory.OBJECT_NOT_VISIBLE,
        ):
            return f"I can't find {_the(target)}, so I'm making a new plan."
        return "That didn't work, so I'm making a new plan."
    if verdict == "abort":
        return f"I had to stop: {_friendly_reason(failure)}" + (
            f" ({_the(target)})." if target else "."
        )
    return ""


def explain_plan(step_count: int, skipped: Optional[list] = None) -> str:
    if step_count == 0:
        return "Nothing to do -- it's already done."
    noun = "step" if step_count == 1 else "small steps"
    text = f"Plan ready: {step_count} {noun}."
    if skipped:
        text += " I skipped what's already done (" + "; ".join(skipped) + ")."
    return text

"""
plan.py (backend/novel)

The strict shape a language-model planner must answer in, and its conversion into the
planner package's `Plan`. A proposal is one of:

    {"goal": "...", "success": [predicate, ...], "steps": [{"action", "target", "container"}]}
    {"question": "..."}        one clarifying question for the user
    {"impossible": "..."}      a plain reason it can't be done

`PLAN_SCHEMA` is sent as the model's structured-output format; `parse_proposal` re-checks
everything anyway (never trust the shape of model output).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from planner.actions import executable_actions
from planner.models import Plan, PlanStep
from verification.predicates import KINDS, Predicate

_STEP = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "target": {"type": "string"},
        "container": {"type": "string"},
    },
    "required": ["action", "target", "container"],
    "additionalProperties": False,
}
_PREDICATE = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(KINDS)},
        "object": {"type": "string"},
        "receptacle": {"type": "string"},
    },
    "required": ["kind", "object", "receptacle"],
    "additionalProperties": False,
}
PLAN_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "goal": {"type": "string"},
        "success": {"type": "array", "items": _PREDICATE},
        "steps": {"type": "array", "items": _STEP},
        "question": {"type": "string"},
        "impossible": {"type": "string"},
    },
    "required": ["goal", "success", "steps", "question", "impossible"],
    "additionalProperties": False,
}


class ProposalError(ValueError):
    """The model's answer was not a usable proposal."""


@dataclass
class NovelStep:
    action: str
    target: Optional[str] = None
    container: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "target": self.target,
            "container": self.container,
        }


@dataclass
class Proposal:
    goal: str = ""
    success: List[Predicate] = field(default_factory=list)
    steps: List[NovelStep] = field(default_factory=list)
    question: Optional[str] = None
    impossible: Optional[str] = None

    @property
    def is_plan(self) -> bool:
        return not self.question and not self.impossible and bool(self.steps)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "success": [p.to_dict() for p in self.success],
            "steps": [s.to_dict() for s in self.steps],
            "question": self.question,
            "impossible": self.impossible,
        }


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text.lower() if text else None


def parse_proposal(data: Any) -> Proposal:
    if not isinstance(data, dict):
        raise ProposalError("the answer was not a JSON object")
    question = str(data.get("question") or "").strip() or None
    impossible = str(data.get("impossible") or "").strip() or None
    steps: List[NovelStep] = []
    for raw in data.get("steps") or []:
        if not isinstance(raw, dict) or not raw.get("action"):
            raise ProposalError("a step has no action")
        steps.append(
            NovelStep(
                str(raw["action"]).strip().lower(),
                _text(raw.get("target")),
                _text(raw.get("container")),
            )
        )
    success: List[Predicate] = []
    for raw in data.get("success") or []:
        try:
            success.append(
                Predicate(
                    kind=str(raw.get("kind")),
                    object=_text(raw.get("object")),
                    receptacle=_text(raw.get("receptacle")),
                )
            )
        except (ValueError, AttributeError) as exc:
            raise ProposalError(f"bad success condition: {exc}") from exc
    if not (question or impossible or steps):
        raise ProposalError("the answer had no steps, question or reason")
    return Proposal(
        goal=str(data.get("goal") or "").strip(),
        success=success,
        steps=steps,
        question=question,
        impossible=impossible,
    )


def to_plan(proposal: Proposal, task_id: str, planner_type: str = "novel") -> Plan:
    from planner.actions import ACTION_REGISTRY

    steps = []
    for i, s in enumerate(proposal.steps, start=1):
        spec = ACTION_REGISTRY.get(s.action)
        params: Dict[str, Any] = {}
        if s.container:
            params["container"] = s.container
        steps.append(
            PlanStep(
                step_id=i,
                action=s.action,
                target=s.target,
                parameters=params,
                description=spec.describe(s.target) if spec else s.action,
            )
        )
    return Plan(
        task_id=task_id,
        planner_type=planner_type,
        goal_summary={"goal": proposal.goal or None},
        steps=steps,
        metadata={
            "success_predicates": [p.to_dict() for p in proposal.success],
            "novel_goal": proposal.goal,
        },
    )


def registry_for_prompt() -> List[Dict[str, Any]]:
    from planner.actions import ACTION_REGISTRY

    return [
        {
            "action": name,
            "arguments": ACTION_REGISTRY[name].arguments,
            "needs": [p.description for p in ACTION_REGISTRY[name].preconditions],
            "does": ACTION_REGISTRY[name].postcondition_descriptions,
        }
        for name in executable_actions()
    ]

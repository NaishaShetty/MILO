"""
planner.py (backend/novel)

`NovelPlanner` -- the "figure it out" planner. It plugs into the orchestrator like any
other planner (so a novel task gets the same execution, reflection, replanning,
narration, traces and goal verification), but its plans come from:

1. a saved skill whose wording matches the command (no model call), else
2. the language-model provider, given the scene, memories, skills, lessons, the action
   registry and -- on a replan -- why the last attempt failed.

Every proposal is validated (`novel.validate`) before it is returned; infeasible ones are
sent back to the model with the problems (within the call budget) or turned into one
clarifying question. Risky steps need the user's OK (`confirm`), budgets are enforced
(steps, model calls, wall time), and after repeated failures a bounded exploration mode
probes the target's affordances and tells the model what changed.

`after_mission(task_state)` stores the outcome: a skill on success, a lesson on failure.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional

from novel.plan import (
    Proposal,
    ProposalError,
    parse_proposal,
    registry_for_prompt,
    to_plan,
)
from novel.providers import PlanRequest, Provider, ProviderError
from novel.safety import Constraints
from novel.skills import SkillChainError, SkillLibrary
from novel.validate import check
from planner.models import PlanningResult, PlanStep, ValidationResult

logger = logging.getLogger(__name__)
Confirm = Callable[[List[Dict[str, Any]]], bool]
_PROBE_ACTIONS = ("open", "turn_on", "turn_off", "close")


def scene_of(metadata: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for o in (metadata or {}).get("objects") or []:
        item: Dict[str, Any] = {
            "name": str(o.get("objectType", "")).lower(),
            "visible": bool(o.get("visible", False)),
            "distance_m": round(float(o.get("distance", -1.0)), 1),
        }
        for key, label in (("isOpen", "open"), ("isToggled", "on")):
            if o.get(key) is not None:
                item[label] = bool(o[key])
        if o.get("pickupable"):
            item["can_pick_up"] = True
        parents = o.get("parentReceptacles") or []
        if parents:
            item["in_or_on"] = [str(p).split("|")[0].lower() for p in parents]
        out.append(item)
    return out


@dataclass
class MissionLog:
    task_id: str
    command: str
    started: float = field(default_factory=time.time)
    attempts: int = 0
    model_calls: int = 0
    probes: int = 0
    source: str = ""  # "skill" | "model"
    skill_template: Optional[str] = None
    caught_infeasible: int = 0
    caught_unsafe: int = 0
    asked: Optional[str] = None
    declined: Optional[str] = None
    feedback: List[str] = field(default_factory=list)
    observations: List[str] = field(default_factory=list)
    proposal: Optional[Proposal] = None
    scene_objects: List[str] = field(default_factory=list)


class NovelPlanner:
    planner_type = "novel"

    def __init__(
        self,
        provider: Provider,
        metadata_source: Callable[[], Optional[Dict[str, Any]]],
        *,
        constraints: Optional[Constraints] = None,
        skills: Optional[SkillLibrary] = None,
        memory_source: Optional[Callable[[str], List[str]]] = None,
        failure_source: Optional[Callable[[], List[str]]] = None,
        probe: Optional[Callable[[str, str], Optional[Dict[str, Any]]]] = None,
        confirm: Optional[Confirm] = None,
    ) -> None:
        self.provider = provider
        self._metadata = metadata_source
        self.constraints = constraints or Constraints.load()
        self.skills = skills
        self._memories = memory_source
        self.failure_source = failure_source
        self._probe = probe
        self._confirm = confirm
        self.log: Optional[MissionLog] = None

    # -- planner interface -------------------------------------------------------------

    def plan(self, task: Any, state: Any, memory_context: Any = None) -> PlanningResult:
        started = time.perf_counter()
        command = (getattr(task, "estimated_goal", None) or task.goal or "").strip()
        task_id = task.task_id or ""
        if self.log is None or self.log.task_id != task_id:
            self.log = MissionLog(task_id, command)
        log = self.log
        log.attempts += 1
        try:
            proposal, note = self._propose(log)
        except _Stop as stop:
            return self._fail(task_id, stop.message, started)
        plan = to_plan(proposal, task_id)
        plan.metadata["novel"] = {
            "source": log.source,
            "model_calls": log.model_calls,
            "note": note,
            "skill": log.skill_template,
        }
        log.proposal = proposal
        return PlanningResult(
            success=True,
            plan=plan,
            validation=ValidationResult(valid=True),
            errors=[],
            planner_type=self.planner_type,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )

    # the orchestrator only calls plan()/replan() for a novel task (never plan_multi)
    replan = plan

    # -- the work --------------------------------------------------------------------------

    def _propose(self, log: MissionLog):
        budgets = self.constraints.budgets
        metadata = self._metadata() or {}
        scene = scene_of(metadata)
        log.scene_objects = sorted({o["name"] for o in scene if o["name"]})
        if time.time() - log.started > budgets.max_wall_s:
            raise _Stop("I ran out of time working this out. Can you show me how?")

        if log.attempts > 1:
            reasons = self.failure_source() if self.failure_source else []
            if reasons:
                log.feedback.append("; ".join(reasons))
            if log.attempts > 2 and self._probe is not None:
                self._explore(log)

        if log.attempts == 1 and self.skills is not None:
            found = self.skills.find(log.command, log.scene_objects)
            if found is not None:
                skill, binding = found
                try:
                    proposal = skill.instantiate(binding, self.skills)
                    result = check(proposal, metadata, self.constraints)
                    if result.ok:
                        log.source, log.skill_template = "skill", skill.template
                        return self._approve(result.fixed or proposal, result, log), (
                            f"I used my '{skill.name}' skill."
                        )
                except (IndexError, ValueError):
                    pass  # skill doesn't fit this scene; ask the model instead

        while True:
            if log.model_calls >= budgets.max_model_calls:
                raise _Stop(
                    "I've thought about this as much as I'm allowed to. "
                    "Can you tell me the steps?"
                )
            request = PlanRequest(
                command=log.command,
                scene=scene,
                holding=next(
                    (
                        str(h.get("objectType", "")).lower()
                        for h in metadata.get("inventoryObjects") or []
                    ),
                    None,
                ),
                actions=registry_for_prompt(),
                memories=self._memories(log.command) if self._memories else [],
                skills=(
                    [s.describe() for s in self.skills.all()[:10]]
                    if self.skills
                    else []
                ),
                lessons=(
                    self.skills.lessons(log.command, log.scene_objects)
                    if self.skills
                    else []
                ),
                feedback=log.feedback + log.observations,
            )
            log.model_calls += 1
            try:
                raw = self.provider.propose(request)
                proposal = parse_proposal(raw)
                if self.skills is not None:
                    proposal = self.skills.expand(proposal)
            except ProviderError as exc:
                raise _Stop(f"{exc}.") from exc
            except (ProposalError, SkillChainError) as exc:
                log.feedback.append(f"your last answer was unusable: {exc}")
                continue
            if proposal.question:
                log.asked = proposal.question
                raise _Stop(proposal.question)
            if proposal.impossible:
                log.declined = proposal.impossible
                raise _Stop(f"I don't think I can: {proposal.impossible}.")
            result = check(proposal, metadata, self.constraints)
            if not result.ok:
                unsafe = any("not allowed" in p for p in result.problems)
                if unsafe:
                    log.caught_unsafe += 1
                else:
                    log.caught_infeasible += 1
                log.feedback.append(
                    "that plan won't work: " + "; ".join(result.problems)
                )
                if log.model_calls >= budgets.max_model_calls:
                    raise _Stop(
                        "I couldn't find a plan that works: "
                        + "; ".join(result.problems)
                        + ". Could you say it another way?"
                    )
                continue
            log.source = "model"
            return self._approve(result.fixed or proposal, result, log), result.fix_note

    def _approve(self, proposal: Proposal, result: Any, log: MissionLog) -> Proposal:
        if result.risky:
            ok = bool(self._confirm and self._confirm(result.risky))
            if not ok:
                log.caught_unsafe += 1
                why = "; ".join(r["why"] for r in result.risky)
                raise _Stop(f"Before I do this I need your OK, because {why}.")
        return proposal

    def _explore(self, log: MissionLog) -> None:
        """Bounded "try and see": probe the failed target's affordances (open, switch on/
        off, close) and record what changed. Only safe, allowed, non-risky probes."""
        if log.proposal is None or self._probe is None:
            return
        targets = [s.target for s in log.proposal.steps if s.target]
        if not targets:
            return
        target = targets[-1]
        for action in _PROBE_ACTIONS:
            if log.probes >= self.constraints.budgets.max_probes:
                break
            if self.constraints.forbidden(action, target) or self.constraints.risk(
                action, target
            ):
                continue
            log.probes += 1
            change = self._probe(action, target)
            if change is None:
                log.observations.append(
                    f"I tried to {action} the {target}: nothing happened"
                )
            else:
                log.observations.append(
                    f"I tried to {action} the {target}: "
                    + (
                        ", ".join(f"{k} -> {v}" for k, v in change.items())
                        or "it worked, nothing visible changed"
                    )
                )

    def _fail(self, task_id: str, message: str, started: float) -> PlanningResult:
        return PlanningResult(
            success=False,
            plan=None,
            validation=None,
            errors=[message],
            planner_type=self.planner_type,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )

    # -- learning --------------------------------------------------------------------------

    def after_mission(self, task_state: Any) -> None:
        log = self.log
        if log is None or self.skills is None or log.task_id != task_state.task_id:
            return
        try:
            if task_state.status.value == "succeeded" and log.proposal is not None:
                self.skills.record_success(log.command, log.scene_objects, log.proposal)
            elif log.proposal is not None:
                self.skills.record_failure(log.command, log.scene_objects)
                tried = ", ".join(
                    f"{s.action} {s.target or ''}".strip() for s in log.proposal.steps
                )
                why = "; ".join(log.feedback[-1:]) or "it did not work"
                self.skills.add_lesson(
                    log.command, log.scene_objects, f"tried [{tried}] -> {why}"
                )
        except Exception:
            logger.warning("novel.learning_failed", exc_info=True)


class _Stop(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


_ = PlanStep

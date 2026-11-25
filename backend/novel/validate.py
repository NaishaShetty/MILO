"""
validate.py (backend/novel)

Checks a proposed plan *before* anything moves:

1. every action is a registry action the executor can run, and allowed by the constraints;
2. every object a step or success condition names exists in the scene;
3. the plan is within the step budget;
4. a symbolic run with the registry's preconditions and effects, starting from the
   simulator's own state, finds no impossible ordering. Where the only problem is a
   missing "go there first" (locate/navigate), the closest feasible plan is produced by
   inserting those steps, with a plain explanation;
5. steps that need the user's OK (risky actions, fragile or dangerous objects) are listed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from execution.resolver import ObjectResolver
from novel.plan import NovelStep, Proposal
from novel.safety import Constraints
from planner.actions import ACTION_REGISTRY, LOCATE, NAVIGATE
from planner.state import WorldState

_resolver = ObjectResolver()
REACH = 1.5
#: Preconditions that only fail because the step's effect already holds
#: ("open" an open fridge): such steps are dropped rather than rejected.
ALREADY_DONE = {"not_open", "is_open", "not_on", "not_off", "not_already_held"}
APPROACH = {"target_located", "target_near", "at_container"}


@dataclass
class Check:
    ok: bool
    problems: List[str] = field(default_factory=list)
    fixed: Optional[Proposal] = None  # closest feasible alternative, if one was made
    fix_note: Optional[str] = None
    risky: List[Dict[str, Any]] = field(default_factory=list)
    unknown_objects: List[str] = field(default_factory=list)


def seed_state(metadata: Optional[Mapping[str, Any]]) -> WorldState:
    """Symbolic start state from simulator metadata (visible -> located, in reach -> near)."""
    state = WorldState.initial()
    meta = dict(metadata or {})
    for obj in meta.get("objects") or []:
        name = str(obj.get("objectType") or "").lower()
        if not name:
            continue
        s = state.object(name)
        s.is_located = bool(obj.get("visible", False))
        distance = float(obj.get("distance", 99.0))
        s.is_near_robot = bool(obj.get("visible", False)) and 0 <= distance <= REACH
        if obj.get("isOpen") is not None:
            s.is_open = bool(obj["isOpen"])
        if obj.get("openable") is not None:
            s.is_openable = bool(obj["openable"])
        if obj.get("isToggled") is not None:
            s.is_on = bool(obj["isToggled"])
    held = meta.get("inventoryObjects") or []
    if held:
        name = str(held[0].get("objectType") or "").lower()
        state.robot_holding = name
        state.object(name).is_held = True
    return state


def _exists(name: Optional[str], meta: Mapping[str, Any]) -> bool:
    return bool(name) and _resolver.resolve(name, dict(meta)) is not None


def _simulate(steps: List[NovelStep], state: WorldState) -> List[tuple]:
    """[(index, step, [failed precondition codes])] for every step that would fail."""
    failures = []
    for i, step in enumerate(steps):
        spec = ACTION_REGISTRY[step.action]
        params = {"container": step.container} if step.container else {}
        missing = spec.check_preconditions(state, step.target, params)
        if missing:
            failures.append((i, step, [p.code for p in missing]))
        spec.apply_effect(state, step.target, params)
    return failures


def _drop_done(steps: List[NovelStep], state: WorldState) -> List[NovelStep]:
    """Removes steps whose effect already holds when they would run."""
    out: List[NovelStep] = []
    work = state.clone()
    for step in steps:
        spec = ACTION_REGISTRY[step.action]
        params = {"container": step.container} if step.container else {}
        codes = {p.code for p in spec.check_preconditions(work, step.target, params)}
        if codes and codes <= ALREADY_DONE:
            continue
        out.append(step)
        spec.apply_effect(work, step.target, params)
    return out


def _insert_approach(steps: List[NovelStep], state: WorldState) -> List[NovelStep]:
    """Adds locate/navigate before any step whose target is not yet located/near."""
    out: List[NovelStep] = []
    work = state.clone()
    for step in steps:
        spec = ACTION_REGISTRY[step.action]
        params = {"container": step.container} if step.container else {}
        codes = [p.code for p in spec.check_preconditions(work, step.target, params)]
        if step.container and "at_container" in codes:
            if not work.object(step.container).is_located:
                out.append(NovelStep(LOCATE, step.container))
                ACTION_REGISTRY[LOCATE].apply_effect(work, step.container, {})
            out.append(NovelStep(NAVIGATE, step.container))
            ACTION_REGISTRY[NAVIGATE].apply_effect(work, step.container, {})
            codes = [
                p.code for p in spec.check_preconditions(work, step.target, params)
            ]
        if step.target and ("target_located" in codes or "target_near" in codes):
            if not work.object(step.target).is_located:
                out.append(NovelStep(LOCATE, step.target))
                ACTION_REGISTRY[LOCATE].apply_effect(work, step.target, {})
            if step.action != NAVIGATE:
                out.append(NovelStep(NAVIGATE, step.target))
                ACTION_REGISTRY[NAVIGATE].apply_effect(work, step.target, {})
        out.append(step)
        spec.apply_effect(work, step.target, params)
    return out


def check(
    proposal: Proposal,
    metadata: Optional[Mapping[str, Any]],
    constraints: Constraints,
) -> Check:
    meta = dict(metadata or {})
    problems: List[str] = []
    unknown: List[str] = []
    for s in proposal.steps:
        spec = ACTION_REGISTRY.get(s.action)
        if spec is None or not spec.executable:
            problems.append(f"I don't have an action called '{s.action}'")
            continue
        reason = constraints.forbidden(s.action, s.target)
        if reason:
            problems.append(reason)
        if spec.requires_target and not s.target:
            problems.append(f"'{s.action}' needs something to act on")
        for name in (s.target, s.container):
            if name and not _exists(name, meta) and name not in unknown:
                unknown.append(name)
        if "container" in spec.required_parameters and not s.container:
            problems.append(f"'{s.action}' needs a place to put it")
    for p in proposal.success:
        for name in (p.object, p.receptacle):
            if name and not _exists(name, meta) and name not in unknown:
                unknown.append(name)
    for name in unknown:
        problems.append(f"I can't see a {name} here")
    if len(proposal.steps) > constraints.budgets.max_steps:
        problems.append(
            f"that plan needs {len(proposal.steps)} steps; my limit is "
            f"{constraints.budgets.max_steps}"
        )
    if problems:
        return Check(False, problems, unknown_objects=unknown)

    start = seed_state(meta)
    failures = _simulate(proposal.steps, start.clone())
    fixed: Optional[Proposal] = None
    note: Optional[str] = None
    if failures:
        repairable = all(
            set(codes) <= APPROACH | ALREADY_DONE for _, _, codes in failures
        )
        if repairable:
            steps = _insert_approach(_drop_done(proposal.steps, start), start)
            if not _simulate(steps, start.clone()):
                fixed = Proposal(proposal.goal, proposal.success, steps)
                dropped = len(steps) < len(proposal.steps) or any(
                    set(c) & ALREADY_DONE for _, _, c in failures
                )
                note = (
                    "I skipped what was already done and added the steps to go to "
                    "things first."
                    if dropped
                    else "I added the steps to go to things before using them."
                )
        if fixed is None:
            i, step, codes = failures[0]
            problems.append(
                f"step {i + 1} ({step.action} {step.target or ''}) can't happen then: "
                + ", ".join(c.replace("_", " ") for c in codes)
            )
            return Check(False, problems)
    final = fixed or proposal
    risky = [
        {"step": i + 1, "action": s.action, "target": s.target, "why": why}
        for i, s in enumerate(final.steps)
        if (why := constraints.risk(s.action, s.target))
    ]
    return Check(True, [], fixed=fixed, fix_note=note, risky=risky)

"""
behavior_tree.py (backend/planner)

Purpose
-------
Implements a general-purpose Behavior Tree (BT) representation --
`Sequence`, `Selector`, `Condition`, `Action`, `Retry` node types -- and
`BehaviorTreePlanner`, a `planner.Planner` implementation that expands a
`SingleTask` into a BT and "ticks" it against a `state.WorldState` to
produce the same `models.PlanStep` sequence a `Plan` needs.

Why a Behavior Tree at all, alongside a flat step list
---------------------------------------------------------
A flat `List[PlanStep]` (as `RuleBasedPlanner` produces) is sufficient
for *this* phase's linear, no-failure-recovery task patterns, but it
cannot express reactive structure -- "try to open it; if that fails,
check whether it's already open before giving up" -- that Phase 5 (and
later, dynamic replanning after execution failure, see this project's
Experiment 5) will need. Building that representation now, and proving
it can regenerate exactly the same validated plans the deterministic
baseline does, is what makes it a credible foundation for Phase 5
rather than a decorative diagram. `BehaviorTreePlanner` is implemented
by composing `RuleBasedPlanner`'s existing goal templates into
`Sequence`/`Condition`/`Action` nodes (never duplicating goal-template
logic) -- ticking the resulting tree yields the identical PlanStep
sequence, byte for byte, that `RuleBasedPlanner` would produce for the
same task, plus the tree structure itself for visualization
(`Plan.metadata["behavior_tree"]`).

Node contract
-------------
Every node's `tick(state)` returns a `NodeStatus` (`SUCCESS`, `FAILURE`,
or `RUNNING`) and, for `Action` nodes, appends the `PlanStep` it
represents to `TickContext.steps` iff its precondition holds -- this is
how a BT "produces a plan" rather than immediately executing one: BT
ticking in this package is a planning-time simulation against a
symbolic `WorldState` (see `state.py`), never a live AI2-THOR call,
preserving the same simulator-independence every other module in this
package guarantees.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from planner.actions import get_action_spec
from planner.exceptions import InvalidTaskError
from planner.models import PlanStep
from planner.planner import Planner
from planner.rule_based import GOAL_HANDLERS, generic_goal
from planner.state import WorldState
from schemas.task import SingleTask


class NodeStatus(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    RUNNING = "running"


@dataclass
class TickContext:
    """Accumulates the PlanSteps a tree traversal produces, plus the WorldState it mutates."""

    state: WorldState
    steps: List[PlanStep] = field(default_factory=list)
    _next_id: int = 1

    def next_step_id(self) -> int:
        step_id = self._next_id
        self._next_id += 1
        return step_id


class BTNode(ABC):
    """Base type for every Behavior Tree node. `name` is used for the visualization export."""

    name: str = "node"

    @abstractmethod
    def tick(self, ctx: TickContext) -> NodeStatus:
        raise NotImplementedError

    def to_dict(self) -> Dict[str, Any]:
        """Serializable tree structure for API/UI visualization (section 17)."""
        return {"type": type(self).__name__, "name": self.name}


class Sequence(BTNode):
    """
    Ticks each child in order; fails and stops at the first child
    that fails. Succeeds only if every child succeeds -- the node type
    a linear plan (e.g. "locate, then navigate, then pickup") is built
    from.
    """

    def __init__(self, name: str, children: List[BTNode]) -> None:
        self.name = name
        self.children = children

    def tick(self, ctx: TickContext) -> NodeStatus:
        for child in self.children:
            status = child.tick(ctx)
            if status != NodeStatus.SUCCESS:
                return status
        return NodeStatus.SUCCESS

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["children"] = [c.to_dict() for c in self.children]
        return d


class Selector(BTNode):
    """
    AKA Fallback: ticks each child in order, returning the first
    non-FAILURE result. Fails only if every child fails -- used to
    express "try the preferred approach; otherwise try an alternative".
    """

    def __init__(self, name: str, children: List[BTNode]) -> None:
        self.name = name
        self.children = children

    def tick(self, ctx: TickContext) -> NodeStatus:
        for child in self.children:
            status = child.tick(ctx)
            if status != NodeStatus.FAILURE:
                return status
        return NodeStatus.FAILURE

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["children"] = [c.to_dict() for c in self.children]
        return d


class Condition(BTNode):
    """Leaf node that succeeds/fails based on a predicate over the current WorldState."""

    def __init__(self, name: str, predicate) -> None:
        self.name = name
        self._predicate = predicate

    def tick(self, ctx: TickContext) -> NodeStatus:
        return NodeStatus.SUCCESS if self._predicate(ctx.state) else NodeStatus.FAILURE


class Retry(BTNode):
    """Decorator: re-ticks its single child up to `max_attempts` times until it succeeds."""

    def __init__(self, name: str, child: BTNode, max_attempts: int = 2) -> None:
        self.name = name
        self.child = child
        self.max_attempts = max_attempts

    def tick(self, ctx: TickContext) -> NodeStatus:
        status = NodeStatus.FAILURE
        for _ in range(self.max_attempts):
            status = self.child.tick(ctx)
            if status == NodeStatus.SUCCESS:
                return status
        return status

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["child"] = self.child.to_dict()
        d["max_attempts"] = self.max_attempts
        return d


class Action(BTNode):
    """
    Leaf node representing one abstract planning action. On tick,
    checks its ActionSpec's preconditions against the current
    WorldState; on success it appends a `PlanStep` to `ctx.steps` and
    applies the action's effect, exactly mirroring
    `validator.PlanValidator`'s own precondition-check-then-apply loop
    so a BT-produced plan validates identically to a rule-based one.
    """

    def __init__(
        self,
        action: str,
        target: Optional[str],
        parameters: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.action = action
        self.target = target
        self.parameters = parameters or {}
        self.name = f"{action}({target or ''})"

    def tick(self, ctx: TickContext) -> NodeStatus:
        spec = get_action_spec(self.action)
        if spec is None:
            return NodeStatus.FAILURE
        if spec.requires_target and not self.target:
            return NodeStatus.FAILURE
        if any(p not in self.parameters for p in spec.required_parameters):
            return NodeStatus.FAILURE
        if spec.check_preconditions(ctx.state, self.target, self.parameters):
            return NodeStatus.FAILURE

        step = PlanStep(
            step_id=ctx.next_step_id(),
            action=self.action,
            target=self.target,
            parameters=self.parameters,
            description=spec.describe(self.target),
            preconditions=[p.description for p in spec.preconditions],
            postconditions=[
                d.format(target=self.target or "")
                for d in spec.postcondition_descriptions
            ],
        )
        spec.apply_effect(ctx.state, self.target, self.parameters)
        ctx.steps.append(step)
        return NodeStatus.SUCCESS

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["action"] = self.action
        d["target"] = self.target
        return d


def _action_node(
    action: str, target: Optional[str], parameters: Optional[Dict[str, Any]] = None
) -> Action:
    return Action(action, target, parameters)


def build_tree_for_task(task: SingleTask, state: Optional[WorldState] = None) -> BTNode:
    """
    Builds a BT `Sequence` of `Action` nodes by re-expanding the same
    goal templates `rule_based.py` uses -- see this module's docstring
    on why goal-template logic itself is never duplicated between the
    two planners. `GOAL_HANDLERS`/`generic_goal` operate on `SingleTask`
    fields (and, since Phase 6.3, a `WorldState` -- see `rule_based.
    py`'s `_apply_memory_hint`) and return `PlanStep`s; this function
    replays each returned step as an `Action` node so ticking reproduces
    the identical sequence, just via BT traversal instead of direct list
    construction. `memory_context` is always `None` here -- see
    `BehaviorTreePlanner._generate_steps`'s docstring for why this
    strategy does not yet consume retrieved memory.
    """
    goal = (task.goal or "").strip().lower()
    if not goal:
        raise InvalidTaskError(
            "Task has no goal; BehaviorTreePlanner cannot plan for it."
        )

    handler = GOAL_HANDLERS.get(goal, generic_goal)
    template_steps = handler(task, state if state is not None else WorldState(), None)
    children: List[BTNode] = [
        _action_node(step.action, step.target, step.parameters)
        for step in template_steps
    ]
    return Sequence(f"{goal}({task.object or task.target or ''})", children)


class BehaviorTreePlanner(Planner):
    """
    Behavior-Tree-backed planning strategy. Produces the same
    `PlanStep` sequence `RuleBasedPlanner` would for a task whose goal
    has a template (see `build_tree_for_task`), while additionally
    exposing the tree itself (via `Plan.metadata["behavior_tree"]`) for
    Phase 5 and section 17's visualization requirement.
    """

    planner_type = "behavior_tree"

    def _generate_steps(
        self, task: SingleTask, state: WorldState, memory_context=None
    ) -> List[PlanStep]:
        # `memory_context` is accepted for interface consistency with
        # `Planner`/`RuleBasedPlanner` (Phase 6.3) but not yet consumed
        # here -- the behavior tree's node structure (Sequence/
        # Selector/Condition/Action) has no equivalent to
        # `RuleBasedPlanner`'s linear step-insertion point without a
        # larger redesign of `build_tree_for_task`, which is out of
        # scope for this phase's "avoid over-engineering" boundary.
        # `RuleBasedPlanner` is this project's memory-conditioned
        # strategy as of 6.3; extending this one is future work.
        tree = build_tree_for_task(task, state)
        ctx = TickContext(state=state.clone())
        tree.tick(ctx)
        self._last_tree = tree
        return ctx.steps

    def _finalize(self, task, state, steps, started_at, memory_context=None):  # type: ignore[override]
        result = super()._finalize(task, state, steps, started_at, memory_context)
        if result.plan is not None and getattr(self, "_last_tree", None) is not None:
            result.plan.metadata["behavior_tree"] = self._last_tree.to_dict()
        return result

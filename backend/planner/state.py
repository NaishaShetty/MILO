"""
state.py (backend/planner)

Purpose
-------
Implements `WorldState`, a lightweight symbolic simulator of the facts a
planner/validator needs to reason about a task: where each named object
is, whether the robot is holding it, whether it has been perceived
("located") and approached ("near"), and whether it is open/closed.
This lets `validator.PlanValidator` and `react.ReActPlanner` replay a
sequence of `PlanStep`s and check preconditions/postconditions WITHOUT
ever running AI2-THOR -- section 9's "Plan State Simulation"
requirement, and the thing that makes this whole package's test suite
able to run with zero simulator dependency.

Why a plain dataclass registry, not a full STRIPS/PDDL state
------------------------------------------------------------
This project needs just enough symbolic state to validate the concrete
action vocabulary in `actions.py` (locate/navigate/pickup/place/open/
close/put_down) -- a generic first-order state representation would be
premature generality this phase does not need yet (see this project's
"do not overengineer" requirement). `ObjectState` is a small, named
set of booleans/strings per object; `WorldState` is a dict of those
plus the robot's own held/location fields. Every attribute here maps
directly onto a precondition or effect declared in `actions.py` --
nothing is speculative.

Auto-vivification
------------------
`WorldState.object(name)` creates a fresh, "unknown" `ObjectState` for
any object name it has not seen before, rather than raising a
`KeyError`. A planner reasoning about "the apple" before ever
perceiving it is the normal case (that is exactly why `locate` is
always the first step for a fresh object) -- treating an unseen object
as "not yet located, not held, not open" is the correct default, not
an error condition.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class ObjectState:
    """
    Everything `actions.py`'s preconditions/effects need to know about
    one named object.

    `is_open` is `None` for an object with no open/closed state at all
    (most objects) as opposed to `False` (a container known to be
    closed) -- `actions.OPEN`'s precondition only ever runs against
    objects a plan actually calls `open`/`close` on, so this
    distinction is never actually load-bearing for validation today,
    but keeping it means a future "this object is not openable" check
    is a one-line addition, not a state-model migration.
    """

    location: Optional[str] = None
    is_located: bool = False
    is_near_robot: bool = False
    is_held: bool = False
    is_open: Optional[bool] = None


@dataclass
class WorldState:
    """
    The full symbolic state a plan is validated against: one
    `ObjectState` per named object, plus the robot's own held/location
    fields (kept on `WorldState` itself, not as a synthetic "robot"
    object, since the robot is not a plannable target of `locate`/
    `navigate`/... the way an object is).
    """

    objects: Dict[str, ObjectState] = field(default_factory=dict)
    robot_holding: Optional[str] = None
    robot_location: Optional[str] = None

    def object(self, name: str) -> ObjectState:
        """
        Returns the `ObjectState` for `name`, auto-vivifying an
        "unknown" one on first reference. See this module's docstring
        for why this must never raise `KeyError`.
        """
        key = name.strip().lower()
        if key not in self.objects:
            self.objects[key] = ObjectState()
        return self.objects[key]

    def has_seen(self, name: str) -> bool:
        """True if `name` has ever been referenced (without vivifying it)."""
        return name.strip().lower() in self.objects

    def clone(self) -> "WorldState":
        """
        Deep copy for speculative simulation (`validator.py` replaying
        a candidate plan, `react.py` trying a proposed next action)
        without mutating the caller's own state.
        """
        return copy.deepcopy(self)

    @classmethod
    def initial(cls) -> "WorldState":
        """
        The default starting state for a fresh planning request: no
        objects perceived yet, robot holding nothing, robot location
        unknown. This is what `factory`/API callers should pass when
        no richer state (e.g. from Phase 2 Vision or a future Memory
        module) is available yet -- see `__init__.py`'s roadmap note on
        scene-graph/memory integration.
        """
        return cls()

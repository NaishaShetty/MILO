"""
resolver.py (backend/execution)

Purpose
-------
Translates a `PlanStep`'s human-readable object reference (Phase 4's
`target`, e.g. `"apple"`, always lowercase free text -- see
`planner.state.WorldState.object()`'s own normalization) into a
concrete AI2-THOR `objectId` (e.g. `"Apple|+00.90|+00.90|-00.28"`) by
reading the simulator's own live `get_metadata()["objects"]` list. This
is the one place in this package that couples an abstract plan to a
concrete scene -- see `__init__.py`'s module docstring for why every
other module in this package stays scene-agnostic.

Why this is a simple name match today, not Vision-grounded
------------------------------------------------------------
Section 2 of the Vision-Language-Robotics roadmap (`backend/vision/`)
already produces `Detection`s with `objectId`s Phase 5 could ground
against instead of a bare AI2-THOR metadata scan -- but wiring
Execution to Vision's live scene graph is explicitly future work (the
same "not yet fused" boundary this project's README already documents
for Planner<->Vision), not a Phase 5 requirement. This resolver's
contract (`resolve(name, metadata) -> Optional[str]`) is deliberately
the seam a future Vision-grounded resolver would replace without
`dispatcher.py`/`controller.py` needing to change at all -- consuming
object identifiers/perception results without coupling the execution
layer to a specific vision model, per the Phase 5 spec's Phase 2
integration note.

Why a small alias table (`_ALIASES`), not smarter fuzzy matching
----------------------------------------------------------------------
A `PlanStep.target` carries whatever noun the user's instruction (and,
in turn, the Planner) used -- e.g. `"refrigerator"`, the exact word the
README's own canonical "store the apple in the refrigerator" example
uses -- while AI2-THOR's real `objectType` for that same object is
`"Fridge"` (confirmed against a real AI2-THOR instance: see
`docs/phases/phase5_execution.md`'s "Post-implementation fixes"
section). A bare case-insensitive match therefore fails on exactly
this project's own headline demo. `_ALIASES` is a small, explicit,
confirmed-only vocabulary bridge for known AI2-THOR naming
divergences -- never a fuzzy/similarity match, which could silently
resolve a step against the wrong object. Only add an alias here once
it is confirmed against a real AI2-THOR scene (as `"refrigerator"` was);
speculative aliases would be exactly the kind of "fabricated
information the simulator cannot provide" the Phase 5 spec prohibits.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Confirmed AI2-THOR objectType divergences from the everyday word a
# task/plan uses for the same object -- see this module's docstring.
# Keys and values are both lowercase; `_candidates()` checks both
# directions so either spelling resolves.
_ALIASES: Dict[str, str] = {
    "refrigerator": "fridge",
}


class ObjectResolver:
    """
    Resolves a `PlanStep` target/parameter name to an AI2-THOR
    `objectId` against one simulator metadata snapshot.
    """

    def resolve(self, name: Optional[str], metadata: Dict[str, Any]) -> Optional[str]:
        """
        Returns the best-matching `objectId` for `name`, or `None` if
        no live object matches.

        `name` already looking like a concrete AI2-THOR id (contains
        `"|"`, AI2-THOR's own id separator) is passed through
        unchanged -- lets a caller that already has a resolved id
        (e.g. a test, or a future Vision-grounded caller) skip the
        name-matching path entirely.
        """
        if not name:
            return None
        if "|" in name:
            return name

        candidates = self._candidates(name, metadata)
        if not candidates:
            return None

        # Prefer the nearest candidate when AI2-THOR reports distance
        # (it does, in every metadata snapshot this project produces --
        # `agent`-relative Euclidean distance) so a scene with more
        # than one instance of an object type resolves to the one the
        # agent is actually closest to/most likely interacting with,
        # rather than an arbitrary list-order pick.
        candidates.sort(key=lambda obj: obj.get("distance", float("inf")))
        return candidates[0].get("objectId")

    def _candidates(self, name: str, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        objects = metadata.get("objects") or []
        target = name.strip().lower()
        # Match either the literal name or its known AI2-THOR alias (in
        # either direction) -- see this module's docstring on `_ALIASES`.
        accepted = {target, _ALIASES.get(target, target)}
        for alias_name, ai2thor_name in _ALIASES.items():
            if ai2thor_name == target:
                accepted.add(alias_name)
        return [
            obj
            for obj in objects
            if isinstance(obj.get("objectType"), str)
            and obj["objectType"].strip().lower() in accepted
        ]

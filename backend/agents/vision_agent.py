"""
vision_agent.py (backend/agents)

Purpose
-------
`VisionAgentWrapper` -- the `BaseAgent` shape around `vision.
vision_agent.VisionAgent` (section 7.6). `perceive()` is an exact
delegation to the wrapped agent's own frozen `perceive()` contract
(see that module's docstring: "every future module... should acquire
perception results by constructing a VisionAgent and calling
perceive(), not by importing a perception internal directly") --
this wrapper does not touch detection, segmentation, depth, tracking,
or scene-graph logic itself.

`locate()` -- the one small addition
-------------------------------------------
The phase brief's example response (`{"found": true, "object_id":
"mug_03", "label": "mug", "position": [...], "confidence": 0.94}`) is
a *reduction* of a `Scene`'s `detections` down to "does the named
object exist, and where" -- exactly what a `PlannerAgent`/
`NavigationAgent` asking "is X visible right now" needs, and exactly
the shape section 7.6 asks for. `locate()` runs `perceive()` then
picks the best-matching, highest-confidence `Detection` whose `label`
matches -- it invents no detection data itself; a scene with no
matching label simply reports `found=False`.
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, List, Optional

from agents.base import BaseAgent
from agents.contracts import AgentError, AgentRequest, AgentResponse, AgentState
from scene.detection import Detection
from scene.scene import Scene
from vision.vision_agent import VisionAgent


class VisionAgentWrapper(BaseAgent):
    """Thin `BaseAgent` wrapper around `vision.vision_agent.VisionAgent`. See module docstring."""

    name = "vision"

    def __init__(self, vision_agent: VisionAgent) -> None:
        super().__init__()
        self._vision_agent = vision_agent

    def perceive(self, prompt: str, *, include_masks: bool = True) -> Scene:
        """Full perception (masks included) -- what the Vision panel wants."""
        self._state = AgentState.ACTIVE
        try:
            if include_masks or not self._supports_include_masks():
                return self._vision_agent.perceive(prompt)
            return self._vision_agent.perceive(prompt, include_masks=False)
        finally:
            self._state = AgentState.IDLE

    def _supports_include_masks(self) -> bool:
        """True if the wrapped agent's `perceive()` accepts `include_masks`
        (a duck-typed/older agent may not -- it then just runs in full)."""
        try:
            params = inspect.signature(self._vision_agent.perceive).parameters
        except (TypeError, ValueError):
            return False
        return "include_masks" in params or any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
        )

    def observe(self, prompt: str) -> Scene:
        """
        Cheap perception for the planning loop: everything
        `ground_world_state` reads (labels, depth, open/closed state)
        without the segmenter. See `PerceptionPipeline.process`.
        """
        return self.perceive(prompt, include_masks=False)

    def held_objects(self) -> Optional[List[str]]:
        """
        The simulator's own `inventoryObjects` as object types
        (`["Apple"]`; `[]` when the hand is empty), or `None` when the
        simulator or its metadata does not report that field -- the
        caller should then fall back to the depth-based held-object
        guess.
        """
        simulator = getattr(self._vision_agent, "simulator", None)
        if simulator is None:
            return None
        try:
            metadata = simulator.get_metadata()
        except Exception:
            return None
        if not isinstance(metadata, dict) or "inventoryObjects" not in metadata:
            return None
        inventory = metadata.get("inventoryObjects") or []
        held: List[str] = []
        for item in inventory:
            if not isinstance(item, dict):
                continue
            # AI2-THOR ids look like "Apple|+01.2|+00.9|-02.1".
            name = (
                item.get("objectType") or str(item.get("objectId") or "").split("|")[0]
            )
            if name:
                held.append(str(name))
        return held

    def locate(self, label: str, *, prompt: Optional[str] = None) -> Dict[str, Any]:
        """
        Runs `perceive()` (prompted with `label` unless `prompt` is
        given) and reduces the resulting `Scene` to the phase brief's
        `{"found", "object_id", "label", "position", "confidence"}`
        shape -- see module docstring.
        """
        scene = self.perceive(prompt or f"{label}.")
        match = self._best_match(scene, label)
        if match is None:
            return {"found": False, "label": label}
        return {
            "found": True,
            "object_id": (
                str(match.tracking_id) if match.tracking_id is not None else None
            ),
            "label": match.label,
            "position": match.position_3d,
            "confidence": match.confidence,
        }

    @staticmethod
    def _best_match(scene: Scene, label: str) -> Optional[Detection]:
        candidates = [d for d in scene.detections if d.label.lower() == label.lower()]
        if not candidates:
            return None
        return max(candidates, key=lambda d: d.confidence)

    def process(self, request: AgentRequest) -> AgentResponse:
        """Supports one generic operation: `"locate"`, taking `payload={"label": ...}`."""
        if request.operation != "locate":
            return AgentResponse(
                request_id=request.request_id,
                success=False,
                error=AgentError(
                    agent=self.name,
                    message=f"unsupported operation: {request.operation!r}",
                ),
            )
        label = request.payload.get("label")
        if not label:
            return AgentResponse(
                request_id=request.request_id,
                success=False,
                error=AgentError(agent=self.name, message="payload.label is required"),
            )
        return AgentResponse(
            request_id=request.request_id, success=True, data=self.locate(label)
        )

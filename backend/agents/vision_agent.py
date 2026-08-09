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

from typing import Any, Dict, Optional

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

    def perceive(self, prompt: str) -> Scene:
        self._state = AgentState.ACTIVE
        try:
            return self._vision_agent.perceive(prompt)
        finally:
            self._state = AgentState.IDLE

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

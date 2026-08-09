"""
test_agents_vision_agent.py

Purpose
-------
Unit tests for `agents.vision_agent.VisionAgentWrapper`: delegation to
`vision.vision_agent.VisionAgent.perceive()`, `locate()`'s
found/not-found reduction, and the generic `process()` "locate"
operation. Uses a minimal fake standing in for `VisionAgent` itself
(only `perceive()` is ever called) -- no AI2-THOR/detector dependency,
matching this suite's existing "fake the boundary" discipline.
"""

from __future__ import annotations

from typing import Optional

from agents.contracts import AgentRequest, AgentState
from agents.vision_agent import VisionAgentWrapper
from scene.detection import Detection
from scene.scene import Scene


class _FakeVisionAgent:
    def __init__(self, scene: Scene) -> None:
        self._scene = scene
        self.last_prompt: Optional[str] = None

    def perceive(self, prompt: str) -> Scene:
        self.last_prompt = prompt
        return self._scene


def _scene_with(*detections: Detection) -> Scene:
    scene = Scene()
    for d in detections:
        scene.add_detection(d)
    return scene


def test_locate_found_returns_highest_confidence_match():
    scene = _scene_with(
        Detection(label="mug", confidence=0.6, bbox=[0, 0, 1, 1], tracking_id=1),
        Detection(
            label="mug",
            confidence=0.94,
            bbox=[0, 0, 1, 1],
            tracking_id=3,
            position_3d=[1.2, 0.0, 2.4],
        ),
    )
    wrapper = VisionAgentWrapper(_FakeVisionAgent(scene))
    result = wrapper.locate("mug")

    assert result == {
        "found": True,
        "object_id": "3",
        "label": "mug",
        "position": [1.2, 0.0, 2.4],
        "confidence": 0.94,
    }
    assert wrapper.get_state() == AgentState.IDLE


def test_locate_not_found_when_no_matching_label():
    wrapper = VisionAgentWrapper(_FakeVisionAgent(Scene()))
    result = wrapper.locate("mug")
    assert result == {"found": False, "label": "mug"}


def test_perceive_delegates_prompt_and_resets_state():
    fake = _FakeVisionAgent(Scene())
    wrapper = VisionAgentWrapper(fake)
    wrapper.perceive("chair. table.")
    assert fake.last_prompt == "chair. table."
    assert wrapper.get_state() == AgentState.IDLE


def test_process_locate_operation_returns_data():
    scene = _scene_with(Detection(label="mug", confidence=0.9, bbox=[0, 0, 1, 1]))
    wrapper = VisionAgentWrapper(_FakeVisionAgent(scene))
    response = wrapper.process(
        AgentRequest(operation="locate", payload={"label": "mug"})
    )
    assert response.success is True
    assert response.data["found"] is True


def test_process_requires_label_payload():
    wrapper = VisionAgentWrapper(_FakeVisionAgent(Scene()))
    response = wrapper.process(AgentRequest(operation="locate", payload={}))
    assert response.success is False

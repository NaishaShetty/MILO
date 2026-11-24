"""
test_perception_cost_and_inventory.py

Phase 1 regression tests:

- the planning loop's perception is cheap (no segmenter / SAM2), while
  the full `perceive()` the Vision panel uses still runs it;
- `ground_world_state` reads the simulator's own `inventoryObjects` for
  the held object, falling back to the depth heuristic only when that
  field is missing.

Simulator- and model-free: stub pipeline stages and a fake simulator.
"""

from __future__ import annotations

from _execution_test_helpers import FakeSimulator

from agents.execution_agent import ExecutionAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from agents.vision_agent import VisionAgentWrapper
from orchestration.orchestrator import Orchestrator
from planner.grounding import ground_world_state
from planner.rule_based import RuleBasedPlanner
from planner.state import WorldState
from scene.detection import Detection
from scene.scene import Scene
from schemas.task import SingleTask
from vision.pipeline.perception_pipeline import PerceptionPipeline
from vision.vision_agent import VisionAgent


class _Stage:
    def __init__(self, name, log):
        self.name, self.log = name, log

    def process(self, image, scene):
        self.log.append(self.name)
        return scene


def _detection(label, depth=None):
    return Detection(label=label, confidence=0.9, bbox=[0, 0, 1, 1], depth=depth)


# -- pipeline / VisionAgent ---------------------------------------------


def test_pipeline_skips_only_the_segmenter_when_masks_are_not_wanted():
    log = []
    pipeline = PerceptionPipeline(
        detector=_Stage("detector", log),
        segmenter=_Stage("segmenter", log),
        depth=_Stage("depth", log),
        tracker=_Stage("tracker", log),
        scene_graph=_Stage("scene_graph", log),
    )

    pipeline.process(None, Scene(), include_masks=False)
    assert log == ["detector", "depth", "tracker", "scene_graph"]

    log.clear()
    pipeline.process(None, Scene())  # default: everything, as before
    assert log == ["detector", "segmenter", "depth", "tracker", "scene_graph"]


def test_vision_agent_perceive_forwards_include_masks():
    log = []

    class _Sim:
        def get_rgb(self):
            return None

    agent = VisionAgent(
        _Sim(),
        detector=_Stage("detector", log),
        segmenter=_Stage("segmenter", log),
    )
    agent.perceive("apple.", include_masks=False)
    assert log == ["detector"]
    log.clear()
    agent.perceive("apple.")
    assert log == ["detector", "segmenter"]


def test_orchestrator_observes_without_masks_and_ui_perceive_keeps_them():
    calls = []

    class _Agent:
        simulator = FakeSimulator()

        def perceive(self, prompt, *, include_masks=True):
            calls.append(include_masks)
            return Scene(detections=[_detection("mug")])

    wrapper = VisionAgentWrapper(_Agent())
    orchestrator = Orchestrator(
        PlannerAgentWrapper(RuleBasedPlanner()),
        ExecutionAgentWrapper(FakeSimulator(objects=[])),
        vision_agent=wrapper,
    )
    orchestrator.run(SingleTask(goal="find", object="mug"))
    assert calls and set(calls) == {False}

    calls.clear()
    wrapper.perceive("mug.")  # what the Vision panel route does
    assert calls == [True]


# -- held object from inventoryObjects -----------------------------------


def test_inventory_is_authoritative_for_the_held_object():
    scene = Scene(detections=[_detection("apple", depth=0.9)])
    state = ground_world_state(scene, held_objects=["Apple"])
    assert state.robot_holding == "apple"
    assert state.object("apple").is_held is True


def test_inventory_beats_a_misleading_depth_guess():
    # A box 0.3m away would be guessed as "held" by the depth heuristic;
    # the inventory says the robot is holding the apple.
    scene = Scene(detections=[_detection("box", depth=0.3), _detection("apple", 1.0)])
    state = ground_world_state(scene, held_objects=["Apple"])
    assert state.robot_holding == "apple"
    assert state.object("box").is_held is False


def test_an_empty_inventory_clears_a_stale_held_object():
    state = WorldState.initial()
    state.robot_holding = "apple"
    state.object("apple").is_held = True
    ground_world_state(
        Scene(detections=[_detection("box", depth=0.3)]), state, held_objects=[]
    )
    assert state.robot_holding is None
    assert state.object("apple").is_held is False


def test_inventory_name_matches_the_planners_spelling():
    state = WorldState.initial()
    state.object("butter knife")
    ground_world_state(Scene(), state, held_objects=["ButterKnife"])
    assert state.robot_holding == "butter knife"


def test_missing_inventory_field_falls_back_to_the_depth_guess():
    scene = Scene(detections=[_detection("box", depth=0.3)])
    state = ground_world_state(scene, held_objects=None)
    assert state.robot_holding == "box"


# -- VisionAgentWrapper.held_objects ---------------------------------------


class _AgentWithMetadata:
    def __init__(self, metadata):
        class _Sim:
            def get_metadata(self_inner):
                return metadata

        self.simulator = _Sim()

    def perceive(self, prompt):
        return Scene()


def test_held_objects_reads_inventory_object_types():
    agent = _AgentWithMetadata({"inventoryObjects": [{"objectType": "Apple"}]})
    assert VisionAgentWrapper(agent).held_objects() == ["Apple"]


def test_held_objects_is_empty_list_for_an_empty_hand():
    agent = _AgentWithMetadata({"inventoryObjects": []})
    assert VisionAgentWrapper(agent).held_objects() == []


def test_held_objects_is_none_when_the_field_is_missing():
    agent = _AgentWithMetadata({"objects": []})
    assert VisionAgentWrapper(agent).held_objects() is None

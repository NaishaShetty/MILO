"""
validate_held_object_depth.py

Purpose
-------
Real distance-data validation of `planner.grounding.HELD_OBJECT_MAX_DEPTH_M`
(0.5m) -- the depth cutoff `_ground_held_object()` uses to decide
whether a detection is "held." That constant was a plausibility
estimate, never measured. This script measures it, the same way
`validate_detection_threshold.py` measured the detection-confidence
threshold instead of guessing: real held-object depths (positive
class) AND real nearby-but-NOT-held depths (negative class -- the
half that was never checked before), across multiple scenes/objects.

Design
------
- **Held samples**: for each scene's `tier2_pickup` objects, a fresh
  AI2-THOR episode navigates to the object and calls
  `simulator.pickup_object()`, then captures a real frame + depth +
  detection. Ground truth: AI2-THOR's own `isPickedUp` metadata
  confirms the object is actually held (not assumed from the action
  call succeeding silently).
- **Not-held-but-close samples**: for each scene's `tier1_locate`
  objects (a different object than any held sample, so this isn't
  trivially the same item), a fresh episode navigates toward the
  object -- the same "stand right next to it" proximity a held object
  would have -- WITHOUT picking it up. Ground truth: `isPickedUp` is
  confirmed `False`.

Both classes go through the same real `GroundingDINODetector`
(`box_threshold=0.25`, the validated production default) +
`SAM2Segmenter` + `GroundTruthDepthEstimator` pipeline production code
uses, not a synthetic depth value.

How to run
-----------
    cd backend
    PYTHONPATH=. python planning_evaluation/validate_held_object_depth.py
"""

from dataclasses import dataclass
from typing import List, Optional

from planning_evaluation.loader import load_tasks
from simulator.simulator import Simulator
from vision.depth.ground_truth_depth_estimator import GroundTruthDepthEstimator
from vision.detectors.grounding_dino_detector import GroundingDINODetector
from vision.scene_graph.heuristic_scene_graph import HeuristicSceneGraph
from vision.segmenters.sam2_segmenter import SAM2Segmenter
from vision.tracking.iou_tracker import IoUTracker
from vision.vision_agent import VisionAgent


@dataclass
class Sample:
    scene: str
    object_name: str
    held: bool
    depth_m: Optional[float]
    detected: bool


def _object_id_for_type(metadata, object_type: str) -> Optional[str]:
    normalized = object_type.strip().lower()
    for obj in metadata["objects"]:
        if obj["objectType"].strip().lower() == normalized:
            return obj["objectId"]
    return None


def _is_picked_up(metadata, object_id: str) -> Optional[bool]:
    for obj in metadata["objects"]:
        if obj["objectId"] == object_id:
            return bool(obj.get("isPickedUp"))
    return None


def _build_agent():
    detector = GroundingDINODetector()  # validated default: box_threshold=0.25
    segmenter = SAM2Segmenter()
    return detector, segmenter


def _capture_depth(
    simulator, detector, segmenter, object_name: str
) -> "tuple[Optional[float], bool]":
    depth_estimator = GroundTruthDepthEstimator(depth_provider=simulator.get_depth)
    agent = VisionAgent(
        simulator,
        detector=detector,
        segmenter=segmenter,
        depth=depth_estimator,
        tracker=IoUTracker(),
        scene_graph=HeuristicSceneGraph(),
    )
    scene = agent.perceive(f"{object_name}.")
    normalized = object_name.strip().lower()
    matches = [
        d
        for d in scene.detections
        if normalized in d.label.replace("##", "").replace(" ", "").strip().lower()
    ]
    if not matches:
        return None, False
    closest = min(
        (d for d in matches if d.depth is not None),
        key=lambda d: d.depth,
        default=None,
    )
    if closest is None:
        return None, True
    return closest.depth, True


def _collect_held_sample(scene: str, object_type: str, detector, segmenter) -> Sample:
    simulator = Simulator(scene=scene, render_depth=True)
    simulator.start()
    try:
        metadata = simulator.get_metadata()
        object_id = _object_id_for_type(metadata, object_type)
        if object_id is None:
            return Sample(scene, object_type, held=True, depth_m=None, detected=False)

        simulator.navigate_to(object_id)
        simulator.pickup_object(object_id)
        metadata = simulator.get_metadata()
        actually_held = _is_picked_up(metadata, object_id)
        if not actually_held:
            print(
                f"  [skip] {scene}/{object_type}: pickup_object did not result in isPickedUp=True"
            )
            return Sample(scene, object_type, held=True, depth_m=None, detected=False)

        depth, detected = _capture_depth(simulator, detector, segmenter, object_type)
        return Sample(scene, object_type, held=True, depth_m=depth, detected=detected)
    finally:
        simulator.stop()


def _collect_not_held_sample(
    scene: str, object_type: str, detector, segmenter
) -> Sample:
    simulator = Simulator(scene=scene, render_depth=True)
    simulator.start()
    try:
        metadata = simulator.get_metadata()
        object_id = _object_id_for_type(metadata, object_type)
        if object_id is None:
            return Sample(scene, object_type, held=False, depth_m=None, detected=False)

        simulator.navigate_to(object_id)
        metadata = simulator.get_metadata()
        actually_held = _is_picked_up(metadata, object_id)
        if actually_held:
            print(
                f"  [skip] {scene}/{object_type}: unexpectedly already isPickedUp=True"
            )
            return Sample(scene, object_type, held=False, depth_m=None, detected=False)

        depth, detected = _capture_depth(simulator, detector, segmenter, object_type)
        return Sample(scene, object_type, held=False, depth_m=depth, detected=detected)
    finally:
        simulator.stop()


def main():
    tasks = load_tasks(version="1.1")
    by_scene_tier2: dict = {}
    by_scene_tier1: dict = {}
    for t in tasks:
        if t.difficulty_tier == "tier2_pickup" and t.object:
            by_scene_tier2.setdefault(t.scene, []).append(t.object)
        if t.difficulty_tier == "tier1_locate" and t.object:
            by_scene_tier1.setdefault(t.scene, []).append(t.object)

    detector, segmenter = _build_agent()

    samples: List[Sample] = []
    scenes = sorted(set(by_scene_tier2) & set(by_scene_tier1))
    for scene in scenes:
        for obj in by_scene_tier2[scene][:1]:  # one held sample per scene
            print(f"--- HELD: {scene}/{obj} ---")
            s = _collect_held_sample(scene, obj, detector, segmenter)
            print(f"  {s}")
            samples.append(s)

        for obj in by_scene_tier1[scene][:1]:  # one not-held sample per scene
            print(f"--- NOT-HELD (close): {scene}/{obj} ---")
            s = _collect_not_held_sample(scene, obj, detector, segmenter)
            print(f"  {s}")
            samples.append(s)

    held = [s for s in samples if s.held and s.depth_m is not None]
    not_held = [s for s in samples if not s.held and s.depth_m is not None]

    print(
        f"\n{'=' * 70}\nHeld-object depth samples ({len(held)} detected/measured of {sum(1 for s in samples if s.held)} attempted)\n{'=' * 70}"
    )
    for s in held:
        print(f"  {s.scene}/{s.object_name}: {s.depth_m:.3f}m")

    print(
        f"\nNot-held-but-close depth samples ({len(not_held)} detected/measured of {sum(1 for s in samples if not s.held)} attempted)"
    )
    for s in not_held:
        print(f"  {s.scene}/{s.object_name}: {s.depth_m:.3f}m")

    if held:
        held_depths = sorted(s.depth_m for s in held)
        print(
            f"\nHeld depths: min={held_depths[0]:.3f} max={held_depths[-1]:.3f} median={held_depths[len(held_depths)//2]:.3f}"
        )
    if not_held:
        nh_depths = sorted(s.depth_m for s in not_held)
        print(
            f"Not-held depths: min={nh_depths[0]:.3f} max={nh_depths[-1]:.3f} median={nh_depths[len(nh_depths)//2]:.3f}"
        )

    if held and not_held:
        print(
            f"\n{'=' * 70}\nCutoff sweep (candidate HELD_OBJECT_MAX_DEPTH_M values)\n{'=' * 70}"
        )
        candidates = sorted({round(x * 0.1, 2) for x in range(2, 25)})
        for cutoff in candidates:
            tp = sum(1 for s in held if s.depth_m <= cutoff)
            fn = sum(1 for s in held if s.depth_m > cutoff)
            fp = sum(1 for s in not_held if s.depth_m <= cutoff)
            tn = sum(1 for s in not_held if s.depth_m > cutoff)
            precision = tp / (tp + fp) if (tp + fp) else float("nan")
            recall = tp / (tp + fn) if (tp + fn) else float("nan")
            print(
                f"cutoff={cutoff:.2f}m  TP={tp} FN={fn} FP={fp} TN={tn}  "
                f"precision={precision:.3f} recall={recall:.3f}"
            )


if __name__ == "__main__":
    main()

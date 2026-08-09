"""
test_scene_graph.py

Purpose
-------
Integration test for Phase 2.8 -- Scene Graph Generation.

Pipeline

Simulator

↓

VisionAgent

↓

PerceptionPipeline

↓

SceneGraph

↓

Print

Why it exists
-------------
Confirms that `HeuristicSceneGraph` works as a real
`PerceptionPipeline` stage on top of real detections and masks (not
just hand-built `Detection` objects), and that `VisionAgent` needed no
code changes beyond passing `scene_graph=` at construction time --
proof that the pipeline's swap-in stage design (documented in
`docs/architecture/perception_pipeline.md`) holds.

Where it fits in the overall architecture
-------------------------------------------
Sits alongside `vision/segmenters/test_segmentation.py` and
`vision/visualization/test_visualizer.py` as the phase-level
integration test for this stage of the perception pipeline.
"""

from simulator.simulator import Simulator
from vision.detectors.grounding_dino_detector import GroundingDINODetector
from vision.scene_graph.heuristic_scene_graph import HeuristicSceneGraph
from vision.segmenters.sam2_segmenter import SAM2Segmenter
from vision.vision_agent import VisionAgent


def main():

    simulator = Simulator()
    simulator.start()

    detector = GroundingDINODetector()
    segmenter = SAM2Segmenter()
    scene_graph = HeuristicSceneGraph()

    vision = VisionAgent(
        simulator,
        detector=detector,
        segmenter=segmenter,
        scene_graph=scene_graph,
    )

    scene = vision.perceive("chair. table. mug. apple. bottle. refrigerator.")

    print()
    print("Detected objects")
    print("-----------------")

    for index, detection in enumerate(scene.detections):
        print(f"[{index}] {detection.label} : {detection.confidence:.2f}")

    print()
    print("Relationships")
    print("-----------------")

    for relationship in scene.relationships:

        subject_label = scene.detections[relationship.subject_id].label
        object_label = scene.detections[relationship.object_id].label

        print(
            f"{subject_label} [{relationship.subject_id}] "
            f"{relationship.predicate} "
            f"{object_label} [{relationship.object_id}] "
            f"(confidence={relationship.confidence:.2f})"
        )

    print()
    print("Relationship count:", len(scene.relationships))

    assert isinstance(scene.relationships, list)

    expected_count = len(scene.detections) * (len(scene.detections) - 1) // 2
    assert len(scene.relationships) == expected_count, (
        f"Expected {expected_count} relationships for "
        f"{len(scene.detections)} detections, got {len(scene.relationships)}."
    )

    print()
    print("Scene now contains relationships: OK")

    simulator.stop()


if __name__ == "__main__":
    main()

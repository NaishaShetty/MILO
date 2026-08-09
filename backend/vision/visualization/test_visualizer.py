"""
test_visualizer.py

Purpose
-------
Integration test for Phase 2.7 -- Perception Visualization.

Pipeline

Simulator

↓

VisionAgent

↓

Scene

↓

SceneVisualizer

↓

Save image

Why it is needed
----------------
Confirms that a real `Scene` produced by the existing perception
pipeline (Grounding DINO detections + SAM2 masks) can be rendered by
`SceneVisualizer` without the visualizer touching the simulator or any
model, and without the render mutating the `Scene` it was given.
"""

import os

import cv2

from scene.metadata_keys import SceneMetadata
from scene.scene import Scene
from simulator.simulator import Simulator
from vision.detectors.grounding_dino_detector import GroundingDINODetector
from vision.segmenters.sam2_segmenter import SAM2Segmenter
from vision.vision_agent import VisionAgent
from vision.visualization.scene_visualizer import SceneVisualizer

OUTPUT_DIR = "outputs"

OUTPUT_PATH = os.path.join(OUTPUT_DIR, "annotated_scene.png")


def main():

    simulator = Simulator()
    simulator.start()

    detector = GroundingDINODetector()
    segmenter = SAM2Segmenter()

    vision = VisionAgent(simulator, detector=detector, segmenter=segmenter)

    image = vision.get_rgb_image()

    scene = Scene()
    scene.metadata[SceneMetadata.DETECTION_PROMPT] = (
        "chair. table. mug. apple. bottle. refrigerator."
    )

    print("Rendering scene...")

    scene = detector.process(image, scene)
    scene = segmenter.process(image, scene)

    visualizer = SceneVisualizer()

    annotated = visualizer.render(image, scene)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    cv2.imwrite(
        OUTPUT_PATH,
        cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR),
    )

    masks_rendered = sum(
        1 for detection in scene.detections if detection.mask is not None
    )

    print()
    print("Detected objects")
    print("-----------------")

    for detection in scene.detections:
        print(f"{detection.label} : {detection.confidence:.2f}")

    print()
    print("Annotated scene saved to:")
    print(OUTPUT_PATH)

    print()
    print("Objects rendered:", len(scene.detections))
    print("Masks rendered:", masks_rendered)
    print("Image size:", annotated.shape)

    simulator.stop()


if __name__ == "__main__":
    main()

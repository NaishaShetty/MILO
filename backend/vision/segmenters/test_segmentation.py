"""
test_segmentation.py

Purpose
-------
Integration test for the complete perception pipeline.

Pipeline

Simulator

↓

Grounding DINO

↓

SAM2

↓

Scene
"""

from scene.metadata_keys import SceneMetadata
from scene.scene import Scene
from simulator.simulator import Simulator
from vision.detectors.grounding_dino_detector import GroundingDINODetector
from vision.segmenters.sam2_segmenter import SAM2Segmenter


def main():

    simulator = Simulator()
    simulator.start()

    image = simulator.get_rgb()

    scene = Scene()

    scene.metadata[SceneMetadata.DETECTION_PROMPT] = (
        "chair. table. mug. apple. " "bottle. refrigerator."
    )

    detector = GroundingDINODetector()

    segmenter = SAM2Segmenter()

    scene = detector.process(image, scene)

    scene = segmenter.process(image, scene)

    print()

    print("Detected Objects")

    print("----------------")

    for detection in scene.detections:

        print()

        print(detection.label)

        print("confidence :", detection.confidence)

        print("mask area :", detection.mask.area)

        print("mask shape :", detection.mask.binary.shape)


if __name__ == "__main__":
    main()

"""
test_scene.py

Purpose
-------
Verifies that Scene objects are correctly created
from detector outputs.
"""

from scene.metadata_keys import SceneMetadata
from scene.scene import Scene
from simulator.simulator import Simulator
from vision.detectors.grounding_dino_detector import GroundingDINODetector


def main():

    simulator = Simulator()
    simulator.start()

    detector = GroundingDINODetector()

    image = simulator.get_rgb()

    scene = Scene()
    scene.metadata[SceneMetadata.DETECTION_PROMPT] = (
        "chair. table. refrigerator. mug. bottle."
    )

    scene = detector.process(image, scene)

    print()

    print("Scene Summary")

    print("----------------")

    print(f"Objects Detected: {len(scene)}")

    print()

    for detection in scene.detections:

        print(detection)

    print()

    print("Labels:")

    print(scene.labels())


if __name__ == "__main__":
    main()

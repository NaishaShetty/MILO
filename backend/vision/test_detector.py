"""
test_detector.py

Purpose
-------
Tests Grounding DINO inference on the robot camera.
"""

import cv2

from scene.metadata_keys import SceneMetadata
from scene.scene import Scene
from simulator.simulator import Simulator
from vision.detectors.grounding_dino_detector import GroundingDINODetector


def main():

    simulator = Simulator()
    simulator.start()

    detector = GroundingDINODetector()

    image = simulator.get_rgb().copy()

    scene = Scene()
    scene.metadata[SceneMetadata.DETECTION_PROMPT] = (
        "chair. table. mug. apple. bottle. refrigerator."
    )

    scene = detector.process(image, scene)

    print()

    print("Detected Objects")

    print("----------------")

    for detection in scene.detections:

        print(detection)

        x1, y1, x2, y2 = map(int, detection.bbox)

        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)

        cv2.putText(
            image,
            detection.label,
            (x1, y1 - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
        )

    cv2.imwrite("detections.png", cv2.cvtColor(image, cv2.COLOR_RGB2BGR))

    print()

    print("Annotated image saved as detections.png")


if __name__ == "__main__":
    main()

"""
test_open_state_classifier.py

Purpose
-------
Real, hands-on verification that `OpenStateClassifier` (this
package's `open_state_classifier.py`) actually distinguishes an open
vs. closed container from a live AI2-THOR camera frame -- not a mocked
model. Matches `vision/test_detector.py`/`vision/segmenters/
test_sam2.py`'s existing convention: a manual integration script
outside `backend/tests/`'s CI-run scope (needs a real simulator + real
GPU model weights), run by hand when verifying this module.

How to run
-----------
    cd backend
    PYTHONPATH=. python vision/state/test_open_state_classifier.py
"""

from scene.metadata_keys import SceneMetadata
from scene.scene import Scene
from simulator.simulator import Simulator
from vision.detectors.grounding_dino_detector import GroundingDINODetector
from vision.state.open_state_classifier import OpenStateClassifier


def _fridge_object_id(metadata):
    return next(
        obj["objectId"] for obj in metadata["objects"] if obj["objectType"] == "Fridge"
    )


def main():
    simulator = Simulator(scene="FloorPlan1")
    simulator.start()

    fridge_id = _fridge_object_id(simulator.get_metadata())
    simulator.navigate_to(fridge_id)

    detector = GroundingDINODetector(box_threshold=0.2, text_threshold=0.2)
    classifier = OpenStateClassifier(detector)

    for expected_open, action in [(False, None), (True, "open"), (False, "close")]:
        if action == "open":
            simulator.open_object(fridge_id)
        elif action == "close":
            simulator.close_object(fridge_id)

        image = simulator.get_rgb().copy()
        scene = Scene()
        scene.metadata[SceneMetadata.DETECTION_PROMPT] = "fridge. refrigerator. door."
        scene = detector.process(image, scene)

        fridge_detections = [
            d
            for d in scene.detections
            if "fridge" in d.label.lower()
            or "refrigerator" in d.label.lower()
            or "door" in d.label.lower()
        ]
        if not fridge_detections:
            print(
                f"action={action!r:8} expected_open={expected_open!s:5} "
                f"NO FRIDGE DETECTION this frame "
                f"(all labels seen: {[d.label for d in scene.detections]})"
            )
            continue

        detection = max(fridge_detections, key=lambda d: d.confidence)
        observed = classifier.classify(image, detection)

        print(
            f"action={action!r:8} expected_open={expected_open!s:5} "
            f"observed_is_open={observed!s:5} "
            f"detector_confidence={detection.confidence:.3f} "
            f"{'OK' if observed == expected_open else 'MISMATCH'}"
        )

    simulator.stop()


if __name__ == "__main__":
    main()

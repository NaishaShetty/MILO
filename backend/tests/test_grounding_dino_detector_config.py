"""
test_grounding_dino_detector_config.py

Purpose
-------
Locks in `GroundingDINODetector`'s validated default `box_threshold`
(0.25, not the old 0.35) without constructing a real detector -- that
would load real model weights, which this project's CI-run test suite
deliberately never does (see `.github/workflows/ci.yml`'s scoping
comment). Inspects the constructor's default arguments directly
instead.

See `planning_evaluation/validate_detection_threshold.py` and
`docs/roadmap.md` for the real precision/recall validation this
default is based on.

How to run
-----------
    cd backend
    python -m pytest tests/test_grounding_dino_detector_config.py -v
"""

import inspect

from vision.detectors.grounding_dino_detector import GroundingDINODetector


def test_default_box_threshold_is_the_validated_value():
    params = inspect.signature(GroundingDINODetector.__init__).parameters
    assert params["box_threshold"].default == 0.25


def test_default_text_threshold_is_unchanged():
    params = inspect.signature(GroundingDINODetector.__init__).parameters
    assert params["text_threshold"].default == 0.25

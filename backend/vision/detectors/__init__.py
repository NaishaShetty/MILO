"""
vision/detectors

Purpose
-------
Home for all box-level object detectors (Grounding DINO today;
future zero-shot or closed-vocabulary detectors later). Every
detector in this package implements `BaseDetector`
(`detectors/base_detector.py`), so callers (`VisionAgent`, tests,
the future planner) can depend on that interface instead of a
specific model.
"""

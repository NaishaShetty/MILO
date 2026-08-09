"""
vision/depth

Purpose
-------
Home for monocular/stereo depth estimation models (e.g. Depth
Anything). Kept separate from `vision/detectors` because depth
estimation runs on the whole frame independently of object
detection -- a `Detection.depth` or `Detection.position_3d` field
will eventually be filled in by looking up this module's output, not
by the detector itself.

Phase 3.x: implemented. See `base_depth_estimator.py` for the shared
interface, `ground_truth_depth_estimator.py` for AI2-THOR ground-truth
depth, and `depth_anything_estimator.py` for the learned/relative-depth
alternative -- both share the same interface so downstream code never
needs to know which one produced a given `Scene`.
"""

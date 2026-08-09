"""
vision/spatial

Purpose
-------
Home for the coordinate-geometry primitives Phase 3.x needs to turn a 2D
pixel + depth reading into a 3D point: `CameraIntrinsics` and the pure
projection functions in `localization.py`.

Why this is its own package, separate from `vision/depth`
-----------------------------------------------------------
Depth estimation (how far is this pixel) and 2D->3D localization (given
that distance, where is the point in space) are different concerns with
different failure modes and different reasons to change: a new depth model
swaps out `vision/depth`'s internals without touching a single line of
projection math, and a camera recalibration or a switch to a different
robot/simulator only ever touches this package. Keeping them separate also
lets `localization.py` be tested with synthetic depth values and no model
at all -- see `backend/tests/test_vision_localization.py`.

Who depends on this
--------------------
`vision/depth/base_depth_estimator.py` calls into `localization.py` to
fill `Detection.position_3d` right after it fills `Detection.depth`.
Nothing else in the perception pipeline needs this package directly.
"""

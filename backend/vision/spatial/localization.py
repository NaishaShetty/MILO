"""
localization.py

Purpose
-------
Pure 2D-pixel + depth -> 3D-point projection math, plus an optional
camera-space -> world-space transform. This is the "2D -> 3D Localization"
subsystem (Phase 3.x.3).

Why this is pure functions, not a class/pipeline stage
-----------------------------------------------------------
Projection has no model weights and no state to hold between frames -- it
is a deterministic function of `(pixel, depth, intrinsics)`. Wrapping it in
a class or a `PerceptionPipeline` stage would add ceremony without adding
capability, and `PerceptionPipeline.__init__`'s signature is frozen (see
`docs/architecture/api_contracts.md`), so a 6th stage isn't an option
without breaking that freeze anyway. Instead, `BaseDepthEstimator` (which
already loops over `scene.detections` to fill `Detection.depth`) calls
`pixel_depth_to_camera_point` directly to also fill
`Detection.position_3d` in the same pass -- see that module's docstring.

Coordinate system (camera space) -- READ BEFORE USING
-----------------------------------------------------------
`pixel_depth_to_camera_point` returns points in **camera space**:

    - Origin: the camera's optical center.
    - +X: right, in the image plane.
    - +Y: down, in the image plane (matches image-row direction -- pixel
      row `v` increases downward, so this avoids a sign flip between pixel
      space and camera space).
    - +Z: forward, out of the camera, into the scene (this is `depth`).
    - Units: meters (matches `Detection.depth`'s units -- see
      `vision/depth/base_depth_estimator.py`).

This is the standard computer-vision pinhole convention (as opposed to a
robotics/ROS convention of X-forward/Z-up) -- chosen because it composes
directly with `CameraIntrinsics` and pixel coordinates without an extra
axis-swap step. Any code consuming `Detection.position_3d` must use this
convention; do not assume ROS or Unity/AI2-THOR world axes here.

World space is a separate, explicit transform (see `camera_to_world`
below) -- never assume camera-space points are already world-relative.
"""

import math
from typing import List, Optional

from vision.spatial.camera_intrinsics import CameraIntrinsics


def pixel_depth_to_camera_point(
    u: float, v: float, depth: float, intrinsics: CameraIntrinsics
) -> List[float]:
    """Projects one pixel + depth reading into a camera-space 3D point.

    Standard pinhole inverse projection:

        X = (u - cx) * depth / fx
        Y = (v - cy) * depth / fy
        Z = depth

    Args:
        u: Pixel x-coordinate (column).
        v: Pixel y-coordinate (row).
        depth: Depth at `(u, v)`, in meters, along the camera's Z axis.
        intrinsics: The camera's `CameraIntrinsics`.

    Returns:
        `[x, y, z]` in camera space (see module docstring for axes/units).

    Raises:
        ValueError: If `depth` is not a finite, positive number -- a
            negative or zero depth is not a physically meaningful 3D
            point, and callers (e.g. `BaseDepthEstimator`) are expected to
            treat that as "invalid depth" and leave `position_3d` unset
            rather than call this function.
    """

    if not math.isfinite(depth) or depth <= 0:
        raise ValueError(
            f"pixel_depth_to_camera_point requires a finite, positive "
            f"depth; got {depth!r}."
        )

    x = (u - intrinsics.cx) * depth / intrinsics.fx
    y = (v - intrinsics.cy) * depth / intrinsics.fy
    z = depth

    return [x, y, z]


def camera_to_world(
    point: List[float],
    agent_position: dict,
    agent_yaw_degrees: float,
    agent_height_offset: float = 0.0,
) -> List[float]:
    """Transforms a camera-space point into AI2-THOR world space.

    Not called anywhere in the perception pipeline today -- provided as a
    documented, independently-tested building block for a future
    planner/world-model that needs object positions relative to the
    world/map rather than the current camera, per the project's world-vs-
    camera-relative documentation requirement. See
    `docs/architecture/spatial_perception.md` for the full writeup.

    AI2-THOR/Unity world space is Y-up (`agent_position` has `x`, `y`, `z`
    with `y` = height); the agent's heading is `agent_yaw_degrees`
    (rotation around the world Y axis, from `event.metadata["agent"]
    ["rotation"]["y"]`).

    Limitation: this rotates only by yaw. It does not account for
    `cameraHorizon` (the camera's up/down tilt) -- AI2-THOR's agent looks
    level by default, and Phase 3.x does not use `look_up`/`look_down`
    before calling this, so the omission is a documented approximation,
    not a bug: a caller localizing objects while the camera is tilted
    should not rely on this function's `y` output without extending it.

    Args:
        point: `[x, y, z]` camera-space point (see module docstring for
            camera-space axes -- +X right, +Y down, +Z forward).
        agent_position: `{"x": ..., "y": ..., "z": ...}`, e.g.
            `event.metadata["agent"]["position"]`.
        agent_yaw_degrees: Agent heading in degrees, e.g.
            `event.metadata["agent"]["rotation"]["y"]`.
        agent_height_offset: Vertical offset (meters) from the agent's
            world `y` to the camera's optical center (0 if unknown/
            negligible for a given robot rig).

    Returns:
        `[world_x, world_y, world_z]` in AI2-THOR world space, meters.
    """

    cam_x, cam_y, cam_z = point

    yaw = math.radians(agent_yaw_degrees)

    # Camera-space +Z (forward) and +X (right) rotate together around the
    # world Y axis by the agent's yaw; camera-space Y (down) flips sign to
    # become a world-space downward offset from the camera height, since
    # world space is Y-up.
    world_x = agent_position["x"] + cam_z * math.sin(yaw) + cam_x * math.cos(yaw)
    world_z = agent_position["z"] + cam_z * math.cos(yaw) - cam_x * math.sin(yaw)
    world_y = agent_position["y"] + agent_height_offset - cam_y

    return [world_x, world_y, world_z]


def bbox_center(bbox: List[float]) -> Optional[List[float]]:
    """Returns the `[u, v]` pixel center of an `[x1, y1, x2, y2]` bbox.

    Shared by `BaseDepthEstimator` (bbox-center depth sampling fallback
    when no mask is available) and any future caller that needs "the
    pixel this detection is located at" without duplicating the
    `(x1+x2)/2, (y1+y2)/2` arithmetic.

    Returns `None` for a degenerate/empty bbox rather than raising, since
    callers already have to handle "no valid pixel to sample" as a normal
    outcome (e.g. a detection with a zero-area box).
    """

    if len(bbox) != 4:
        return None

    x1, y1, x2, y2 = bbox

    if x2 <= x1 or y2 <= y1:
        return None

    return [(x1 + x2) / 2.0, (y1 + y2) / 2.0]

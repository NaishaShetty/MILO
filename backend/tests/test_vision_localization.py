"""
test_vision_localization.py

Purpose
-------
Deterministic, model-free tests for `vision/spatial/camera_intrinsics.py`
and `vision/spatial/localization.py` -- known camera parameters, known
depth, known pixel, expected 3D coordinate, per the project's testing
requirements for 2D->3D localization.
"""

import pytest

from vision.spatial.camera_intrinsics import CameraIntrinsics
from vision.spatial.localization import (
    bbox_center,
    camera_to_world,
    pixel_depth_to_camera_point,
)


def _identity_intrinsics() -> CameraIntrinsics:
    # fx=fy=1, cx=cy=0 makes the projection arithmetic trivial to verify
    # by hand: X = u * depth, Y = v * depth, Z = depth.
    return CameraIntrinsics(fx=1.0, fy=1.0, cx=0.0, cy=0.0, width=100, height=100)


def test_pixel_at_principal_point_projects_straight_ahead():
    intrinsics = _identity_intrinsics()

    point = pixel_depth_to_camera_point(0.0, 0.0, 2.0, intrinsics)

    assert point == [0.0, 0.0, 2.0]


def test_pixel_offset_scales_with_depth():
    intrinsics = _identity_intrinsics()

    point = pixel_depth_to_camera_point(3.0, 4.0, 5.0, intrinsics)

    assert point == [15.0, 20.0, 5.0]


def test_realistic_intrinsics_known_coordinate():
    # width=height=100, fov=90deg -> fy = 50 / tan(45deg) = 50.
    intrinsics = CameraIntrinsics.from_ai2thor_fov(
        width=100, height=100, fov_degrees=90.0
    )

    assert intrinsics.fx == pytest.approx(50.0)
    assert intrinsics.cx == 50.0
    assert intrinsics.cy == 50.0

    # A pixel exactly at the principal point, at 2m depth, is directly
    # ahead: X=0, Y=0, Z=2.
    point = pixel_depth_to_camera_point(50.0, 50.0, 2.0, intrinsics)
    assert point == pytest.approx([0.0, 0.0, 2.0])


def test_invalid_depth_raises():
    intrinsics = _identity_intrinsics()

    with pytest.raises(ValueError):
        pixel_depth_to_camera_point(0.0, 0.0, 0.0, intrinsics)

    with pytest.raises(ValueError):
        pixel_depth_to_camera_point(0.0, 0.0, -1.0, intrinsics)

    with pytest.raises(ValueError):
        pixel_depth_to_camera_point(0.0, 0.0, float("nan"), intrinsics)


def test_bbox_center_known_box():
    assert bbox_center([10.0, 20.0, 30.0, 40.0]) == [20.0, 30.0]


def test_bbox_center_degenerate_box_returns_none():
    assert bbox_center([10.0, 20.0, 10.0, 40.0]) is None
    assert bbox_center([10.0, 20.0, 30.0, 20.0]) is None


def test_bbox_center_wrong_length_returns_none():
    assert bbox_center([1.0, 2.0, 3.0]) is None


def test_camera_to_world_no_rotation_no_offset():
    # Facing yaw=0: camera +Z (forward) maps to world +Z, camera +X
    # (right) maps to world +X, camera +Y (down) flips to world -Y.
    world = camera_to_world(
        point=[1.0, 2.0, 3.0],
        agent_position={"x": 0.0, "y": 0.0, "z": 0.0},
        agent_yaw_degrees=0.0,
    )

    assert world == pytest.approx([1.0, -2.0, 3.0])


def test_camera_to_world_translates_by_agent_position():
    world = camera_to_world(
        point=[0.0, 0.0, 1.0],
        agent_position={"x": 5.0, "y": 1.5, "z": -2.0},
        agent_yaw_degrees=0.0,
    )

    assert world == pytest.approx([5.0, 1.5, -1.0])


def test_camera_to_world_90_degree_yaw():
    # Facing yaw=90deg, "forward" (camera +Z) points along world +X.
    world = camera_to_world(
        point=[0.0, 0.0, 1.0],
        agent_position={"x": 0.0, "y": 0.0, "z": 0.0},
        agent_yaw_degrees=90.0,
    )

    assert world[0] == pytest.approx(1.0, abs=1e-9)
    assert world[2] == pytest.approx(0.0, abs=1e-9)


def test_camera_to_world_height_offset():
    world = camera_to_world(
        point=[0.0, 0.0, 1.0],
        agent_position={"x": 0.0, "y": 0.0, "z": 0.0},
        agent_yaw_degrees=0.0,
        agent_height_offset=0.6,
    )

    assert world[1] == pytest.approx(0.6)

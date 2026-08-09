"""
test_vision_depth.py

Purpose
-------
Deterministic, synthetic-input tests for the depth subsystem
(`vision/depth/`). No real model is downloaded or run -- CI must stay
network-independent and GPU-free (see `.github/workflows/ci.yml`'s
scope note), so `DepthAnythingEstimator` itself (which loads a real
model in `__init__`) is never instantiated here; only its pure
`relative_to_pseudo_depth` conversion function is tested directly.
`BaseDepthEstimator`'s shared object-depth-extraction logic is exercised
through a minimal fake subclass and through `GroundTruthDepthEstimator`,
both of which take a synthetic depth map/provider and no model weights.
"""

import numpy as np
import pytest

from scene.detection import Detection
from scene.mask import Mask
from scene.metadata_keys import SceneMetadata
from scene.scene import Scene
from vision.depth.base_depth_estimator import BaseDepthEstimator
from vision.depth.depth_anything_estimator import relative_to_pseudo_depth
from vision.depth.depth_config import DepthConfig
from vision.depth.ground_truth_depth_estimator import GroundTruthDepthEstimator
from vision.spatial.camera_intrinsics import CameraIntrinsics


class _FakeDepthEstimator(BaseDepthEstimator):
    """Minimal concrete `BaseDepthEstimator` returning a fixed synthetic
    depth map -- exercises the shared template method without any real
    depth source."""

    def __init__(self, depth_map, **kwargs):
        super().__init__(**kwargs)
        self._depth_map = depth_map

    @property
    def source_name(self):
        return "fake"

    def _get_depth_map(self, image, scene):
        return self._depth_map


def _make_image(height=10, width=10):
    return np.zeros((height, width, 3), dtype=np.uint8)


def test_process_sets_depth_image_and_source_metadata():
    depth_map = np.full((10, 10), 2.0, dtype=float)
    estimator = _FakeDepthEstimator(depth_map)
    scene = Scene()

    result = estimator.process(_make_image(), scene)

    assert result is scene
    assert scene.depth_image is depth_map
    assert scene.metadata[SceneMetadata.DEPTH_SOURCE] == "fake"


def test_process_with_no_depth_map_leaves_detections_untouched():
    estimator = _FakeDepthEstimator(None)
    scene = Scene()
    scene.add_detection(Detection(label="mug", confidence=0.9, bbox=[1, 1, 3, 3]))

    result = estimator.process(_make_image(), scene)

    assert result.depth_image is None
    assert result.detections[0].depth is None


def test_bbox_depth_extraction_uses_median_of_valid_pixels():
    depth_map = np.full((10, 10), 3.0, dtype=float)
    # A patch of invalid (negative) depth inside the bbox -- median
    # should still recover 3.0 as long as most pixels stay valid.
    depth_map[1, 1] = -1.0

    estimator = _FakeDepthEstimator(
        depth_map,
        config=DepthConfig(min_valid_pixel_ratio=0.1, max_plausible_depth_meters=20.0),
    )
    scene = Scene()
    scene.add_detection(Detection(label="mug", confidence=0.9, bbox=[0, 0, 4, 4]))

    result = estimator.process(_make_image(), scene)

    assert result.detections[0].depth == pytest.approx(3.0)
    assert result.detections[0].attributes["depth_valid_pixel_ratio"] > 0.9


def test_mask_used_over_bbox_when_available():
    depth_map = np.full((10, 10), 5.0, dtype=float)
    depth_map[0:10, 0:5] = 1.0  # left half reads a different depth

    mask_binary = np.zeros((10, 10), dtype=bool)
    mask_binary[0:10, 5:10] = True  # mask covers only the right half (depth=5)

    estimator = _FakeDepthEstimator(depth_map)
    scene = Scene()
    detection = Detection(
        label="mug",
        confidence=0.9,
        bbox=[0, 0, 10, 10],
        mask=Mask(binary=mask_binary, area=int(mask_binary.sum()), bbox=[0, 0, 10, 10]),
    )
    scene.add_detection(detection)

    result = estimator.process(_make_image(), scene)

    assert result.detections[0].depth == pytest.approx(5.0)


def test_insufficient_valid_pixels_leaves_depth_none():
    depth_map = np.full((10, 10), -1.0, dtype=float)  # entirely invalid

    estimator = _FakeDepthEstimator(depth_map)
    scene = Scene()
    scene.add_detection(Detection(label="mug", confidence=0.9, bbox=[0, 0, 4, 4]))

    result = estimator.process(_make_image(), scene)

    assert result.detections[0].depth is None
    assert result.detections[0].attributes["depth_valid_pixel_ratio"] == 0.0


def test_bbox_outside_depth_map_bounds_leaves_depth_none():
    depth_map = np.full((10, 10), 2.0, dtype=float)

    estimator = _FakeDepthEstimator(depth_map)
    scene = Scene()
    scene.add_detection(
        Detection(label="mug", confidence=0.9, bbox=[100, 100, 110, 110])
    )

    result = estimator.process(_make_image(), scene)

    assert result.detections[0].depth is None


def test_position_3d_filled_when_intrinsics_configured():
    depth_map = np.full((10, 10), 2.0, dtype=float)
    intrinsics = CameraIntrinsics(fx=1.0, fy=1.0, cx=0.0, cy=0.0, width=10, height=10)

    estimator = _FakeDepthEstimator(depth_map, intrinsics=intrinsics)
    scene = Scene()
    scene.add_detection(Detection(label="mug", confidence=0.9, bbox=[0, 0, 4, 4]))

    result = estimator.process(_make_image(), scene)

    detection = result.detections[0]
    assert detection.position_3d is not None
    assert detection.position_3d[2] == pytest.approx(2.0)  # Z == depth


def test_position_3d_stays_none_without_intrinsics():
    depth_map = np.full((10, 10), 2.0, dtype=float)

    estimator = _FakeDepthEstimator(depth_map)
    scene = Scene()
    scene.add_detection(Detection(label="mug", confidence=0.9, bbox=[0, 0, 4, 4]))

    result = estimator.process(_make_image(), scene)

    assert result.detections[0].position_3d is None


# ---------------------------------------------------------------------------
# GroundTruthDepthEstimator
# ---------------------------------------------------------------------------


def test_ground_truth_estimator_uses_depth_provider():
    depth_map = np.full((10, 10), 4.0, dtype=float)
    estimator = GroundTruthDepthEstimator(depth_provider=lambda: depth_map)
    scene = Scene()
    scene.add_detection(Detection(label="apple", confidence=0.9, bbox=[0, 0, 4, 4]))

    result = estimator.process(_make_image(), scene)

    assert result.metadata[SceneMetadata.DEPTH_SOURCE] == "ground_truth"
    assert result.detections[0].depth == pytest.approx(4.0)


def test_ground_truth_estimator_handles_unavailable_depth():
    estimator = GroundTruthDepthEstimator(depth_provider=lambda: None)
    scene = Scene()

    result = estimator.process(_make_image(), scene)

    assert result.depth_image is None
    assert result.metadata[SceneMetadata.DEPTH_SOURCE] == "ground_truth"


# ---------------------------------------------------------------------------
# Depth Anything's pure relative -> pseudo-depth conversion
# ---------------------------------------------------------------------------


def test_relative_to_pseudo_depth_inverts_ordering():
    # Larger relative value ("closer" in Depth Anything's convention)
    # must map to a smaller pseudo-depth value (matching ground truth's
    # "smaller == closer" meters convention).
    relative = np.array([10.0, 1.0, 0.1])

    pseudo = relative_to_pseudo_depth(relative)

    assert pseudo[0] < pseudo[1] < pseudo[2]


def test_relative_to_pseudo_depth_handles_zero_without_error():
    relative = np.array([0.0])

    pseudo = relative_to_pseudo_depth(relative)

    assert np.isfinite(pseudo).all()

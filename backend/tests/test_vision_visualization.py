"""
test_vision_visualization.py

Purpose
-------
Deterministic tests for the Phase 3.x visualization extensions:
`SceneVisualizer`'s optional tracking-id/depth label suffixes (backward
compatible with Phase 2's plain "<label> <confidence>" output), and the
new `DepthVisualizer` colormap + legend. Synthetic images/scenes only.
"""

import numpy as np

from scene.detection import Detection
from scene.scene import Scene
from vision.visualization.depth_visualizer import DepthVisualizer
from vision.visualization.scene_visualizer import SceneVisualizer


def _image(height=20, width=20):
    return np.zeros((height, width, 3), dtype=np.uint8)


def test_scene_visualizer_renders_without_tracking_or_depth():
    scene = Scene()
    scene.add_detection(Detection(label="mug", confidence=0.9, bbox=[1, 1, 10, 10]))

    annotated = SceneVisualizer().render(_image(), scene)

    assert annotated.shape == (20, 20, 3)


def test_scene_visualizer_does_not_mutate_scene_or_image():
    image = _image()
    scene = Scene()
    scene.add_detection(Detection(label="mug", confidence=0.9, bbox=[1, 1, 10, 10]))

    original_image = image.copy()
    SceneVisualizer().render(image, scene)

    assert np.array_equal(image, original_image)
    assert scene.detections[0].tracking_id is None


def test_scene_visualizer_handles_tracking_id_and_depth_present():
    scene = Scene()
    detection = Detection(label="mug", confidence=0.9, bbox=[1, 1, 10, 10])
    detection.tracking_id = 3
    detection.depth = 1.84
    scene.add_detection(detection)

    # Should not raise -- exercises the tracking_id/#-suffix and
    # depth/m-suffix label-drawing branches.
    annotated = SceneVisualizer().render(_image(), scene)
    assert annotated.shape == (20, 20, 3)


def test_depth_visualizer_returns_none_when_no_depth_image():
    scene = Scene()

    image, legend = DepthVisualizer().render(None, scene)

    assert image is None
    assert legend is None


def test_depth_visualizer_returns_legend_with_correct_min_max():
    depth_map = np.full((10, 10), 2.0, dtype=float)
    depth_map[0, 0] = 5.0

    scene = Scene()
    scene.depth_image = depth_map

    image, legend = DepthVisualizer().render(None, scene)

    assert image is not None
    assert image.shape == (10, 10, 3)
    assert legend.min_depth_m == 2.0
    assert legend.max_depth_m == 5.0


def test_depth_visualizer_handles_flat_depth_map_without_error():
    depth_map = np.full((5, 5), 3.0, dtype=float)

    scene = Scene()
    scene.depth_image = depth_map

    image, legend = DepthVisualizer().render(None, scene)

    assert image is not None
    assert legend.min_depth_m == legend.max_depth_m == 3.0


def test_depth_visualizer_handles_all_invalid_depth():
    depth_map = np.full((5, 5), -1.0, dtype=float)

    scene = Scene()
    scene.depth_image = depth_map

    image, legend = DepthVisualizer().render(None, scene)

    assert image is None
    assert legend is None

"""Phase C: detector classes, YOLO labels, ONNX decoding, fallback logic, metrics and splits."""

from __future__ import annotations

import numpy as np
import pytest

from learning.detector.classes import CLASSES, class_of
from learning.detector.collect import MIN_BOX_PX, yolo_line
from learning.detector.eval_detector import average_precision, iou, score
from learning.detector.fast_detector import (
    FallbackDetector,
    build_fast_detector,
    decode,
    letterbox,
)
from learning.detector.train_detector import scene_split
from scene.metadata_keys import SceneMetadata
from scene.scene import Scene
from vision.pipeline.perception_pipeline import PerceptionPipeline
from vision.vision_agent import VisionAgent


def test_classes_cover_the_task_objects_and_merge_table_types():
    for name in (
        "apple",
        "mug",
        "refrigerator",
        "table",
        "countertop",
        "light switch",
        "faucet",
    ):
        assert name in CLASSES
    assert class_of("DiningTable") == class_of("SideTable") == "table"
    assert class_of("Fridge") == "refrigerator" and class_of("Floor") is None
    assert CLASSES == sorted(set(CLASSES))


def test_yolo_labels_are_normalised_clipped_and_drop_tiny_boxes():
    line = yolo_line(3, [100.0, 50.0, 300.0, 250.0])
    cls, cx, cy, w, h = line.split()
    assert (
        cls == "3"
        and float(cx) == pytest.approx(200 / 640)
        and float(h) == pytest.approx(200 / 480)
    )
    clipped = yolo_line(0, [-20.0, -20.0, 100.0, 100.0])
    assert float(clipped.split()[1]) == pytest.approx(
        50 / 640
    )  # box clipped to the frame
    assert yolo_line(0, [0, 0, MIN_BOX_PX - 1, 50]) is None


def test_letterbox_keeps_aspect_ratio_and_decode_maps_back_to_pixels():
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    tensor, scale, pad_x, pad_y = letterbox(image, 480)
    assert (
        tensor.shape == (1, 3, 480, 480)
        and scale == pytest.approx(0.75)
        and (pad_x, pad_y) == (0, 60)
    )
    # A fake network output: one box centred at (240, 240) in letterbox space, class 2.
    nc = 5
    out = np.zeros((1, 4 + nc, 3), dtype=np.float32)
    out[0, :4, 0] = [240, 240, 60, 60]
    out[0, 4 + 2, 0] = 0.9
    out[0, :4, 1] = [242, 241, 60, 60]  # a duplicate that NMS must remove
    out[0, 4 + 2, 1] = 0.6
    dets = decode(out, scale, pad_x, pad_y, image.shape, conf=0.25)
    assert len(dets) == 1 and dets[0]["class_id"] == 2
    x1, y1, x2, y2 = dets[0]["bbox"]
    assert (x1, x2) == (
        pytest.approx(280.0, abs=1),
        pytest.approx(360.0, abs=1),
    )  # (240-30)/0.75 .. (240+30)/0.75
    assert (y1, y2) == (
        pytest.approx(200.0, abs=1),
        pytest.approx(280.0, abs=1),
    )  # shifted back by the 60px pad
    assert (
        decode(
            np.zeros((1, 9, 4), dtype=np.float32),
            scale,
            pad_x,
            pad_y,
            image.shape,
            0.25,
        )
        == []
    )


class StubFast:
    classes = ["apple", "refrigerator", "mug"]

    def __init__(self, found):
        self.found = found

    def detect(self, image):
        return self.found


class StubSlow:
    def __init__(self):
        self.calls = 0

    def process(self, image, scene):
        self.calls += 1
        scene.metadata["slow"] = True
        return scene


def _scene(prompt):
    s = Scene()
    s.metadata[SceneMetadata.DETECTION_PROMPT] = prompt
    return s


def _det(cls, conf):
    return {"class_id": cls, "confidence": conf, "bbox": [0, 0, 50, 50]}


def test_fallback_uses_the_fast_detector_when_it_is_confident_and_finds_the_target():
    slow = StubSlow()
    fb = FallbackDetector(StubFast([_det(0, 0.9)]), slow)
    scene = fb.process(None, _scene("apple."))
    assert slow.calls == 0 and [d.label for d in scene.detections] == ["apple"]
    assert fb.stats == {"frames": 1, "fallbacks": 0}


@pytest.mark.parametrize(
    "found, prompt",
    [([_det(0, 0.9)], "mug."), ([_det(0, 0.2)], "apple."), ([], "apple.")],
)
def test_fallback_goes_to_grounding_dino_when_unsure_or_the_target_is_missing(
    found, prompt
):
    slow = StubSlow()
    fb = FallbackDetector(StubFast(found), slow)
    scene = fb.process(None, _scene(prompt))
    assert slow.calls == 1 and scene.metadata["slow"] and fb.stats["fallbacks"] == 1


def test_everyday_names_in_the_prompt_match_detector_classes():
    slow = StubSlow()
    FallbackDetector(StubFast([_det(1, 0.9)]), slow).process(None, _scene("fridge."))
    assert slow.calls == 0  # "fridge" is the detector's "refrigerator"


def test_a_missing_or_broken_model_means_no_fast_detector(tmp_path):
    slow = StubSlow()
    assert build_fast_detector(tmp_path / "nope", slow) is None
    (tmp_path / "detector.onnx").write_bytes(b"garbage")
    (tmp_path / "classes.json").write_text('{"classes": ["a"]}')
    assert build_fast_detector(tmp_path, slow) is None
    assert build_fast_detector(tmp_path, slow, env_flag=False) is None


def test_the_cheap_observe_path_uses_the_fast_detector_and_the_full_path_does_not():
    calls = []

    class Det:
        def __init__(self, name):
            self.name = name

        def process(self, image, scene):
            calls.append(self.name)
            return scene

    class Sim:
        def get_rgb(self):
            return np.zeros((4, 4, 3), dtype=np.uint8)

    agent = VisionAgent(Sim(), detector=Det("dino"), fast_detector=Det("fast"))
    agent.perceive("apple.", include_masks=False)
    agent.perceive("apple.")
    assert calls == ["fast", "dino"]
    assert (
        VisionAgent(Sim(), detector=Det("dino")).fast_pipeline is None
    )  # no flag, no change
    _ = PerceptionPipeline


def test_average_precision_and_scoring():
    assert (
        iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
        and iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0
    )
    assert average_precision([(0.9, True), (0.8, True)], 2) == pytest.approx(1.0)
    assert average_precision([(0.9, False), (0.8, True)], 1) == pytest.approx(0.5)
    gt = [
        {"cls": "apple", "bbox": [0, 0, 10, 10]},
        {"cls": "mug", "bbox": [20, 20, 40, 40]},
    ]
    good = [
        {"cls": "apple", "confidence": 0.9, "bbox": [0, 0, 10, 10]},
        {"cls": "mug", "confidence": 0.8, "bbox": [20, 20, 40, 40]},
    ]
    half = good[:1] + [{"cls": "mug", "confidence": 0.7, "bbox": [100, 100, 120, 120]}]
    assert score([(gt, good)], ["apple", "mug"])["recall50"] == 1.0
    assert score([(gt, half)], ["apple", "mug"])["recall50"] == 0.5


def test_detector_splits_are_by_scene_with_no_overlap():
    scenes = [f"FloorPlan{i}" for i in range(1, 121)]
    split = scene_split(scenes, seed=0)
    assert sum(len(v) for v in split.values()) == 120
    assert (
        not set(split["train"]) & set(split["val"])
        and not set(split["train"]) & set(split["test"])
        and not set(split["val"]) & set(split["test"])
    )
    assert len(split["test"]) == 24 and scene_split(scenes, 0) == split

"""SAM2Segmenter segments every box of a frame in one model call (no real weights)."""

from __future__ import annotations

import numpy as np
import torch

from scene.detection import Detection
from scene.scene import Scene
from vision.segmenters.sam2_segmenter import SAM2Segmenter


class _Inputs(dict):
    def to(self, device):
        return self


class FakeProcessor:
    def __init__(self):
        self.box_calls = []

    def __call__(self, images, input_boxes, return_tensors):
        self.box_calls.append(input_boxes)
        return _Inputs(original_sizes=torch.tensor([[4, 6]]), n=len(input_boxes[0]))

    def post_process_masks(self, pred_masks, original_sizes):
        return [pred_masks]


class FakeModel:
    def __init__(self):
        self.calls = 0

    def __call__(self, n, original_sizes, multimask_output):
        self.calls += 1
        masks = torch.zeros((n, 1, 4, 6), dtype=torch.bool)
        for i in range(n):
            masks[i, 0, 0, : i + 1] = True  # box i's mask has i + 1 pixels
        return type("Out", (), {"pred_masks": masks})()


def _segmenter():
    seg = SAM2Segmenter.__new__(SAM2Segmenter)  # skip loading real weights
    seg.device = "cpu"
    seg.processor, seg.model = FakeProcessor(), FakeModel()
    return seg


def _scene(n):
    s = Scene()
    for i in range(n):
        s.add_detection(Detection(label=f"obj{i}", confidence=0.9,
                                  bbox=[i, i, i + 2, i + 2]))  # fmt: skip
    return s


def test_all_boxes_go_through_one_model_call_and_masks_stay_in_order():
    seg = _segmenter()
    scene = seg.process(np.zeros((4, 6, 3), dtype=np.uint8), _scene(3))
    assert seg.model.calls == 1
    # one image, all three boxes as its prompts
    assert seg.processor.box_calls == [[[[0, 0, 2, 2], [1, 1, 3, 3], [2, 2, 4, 4]]]]
    assert [d.mask.area for d in scene.detections] == [1, 2, 3]
    assert [d.mask.bbox for d in scene.detections] == [d.bbox for d in scene.detections]


def test_a_frame_with_no_detections_makes_no_call():
    seg = _segmenter()
    seg.process(np.zeros((4, 6, 3), dtype=np.uint8), Scene())
    assert seg.model.calls == 0

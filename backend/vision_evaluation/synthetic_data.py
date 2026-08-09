"""
synthetic_data.py

Purpose
-------
Deterministic (seeded) synthetic depth maps and detection sequences for
the perception benchmark -- see this package's `__init__.py` for why no
real labeled dataset is used. Every generator here takes an explicit
`seed` and returns plain data structures the real project code
(`BaseDepthEstimator`, `IoUTracker`) can be run against unmodified.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List

import numpy as np

from scene.detection import Detection


@dataclass(frozen=True)
class SyntheticDepthCase:
    """One synthetic depth-evaluation case: a ground-truth depth map and
    a noisy "predicted" depth map of the same shape."""

    ground_truth_depth: np.ndarray
    predicted_depth: np.ndarray
    detections: List[Detection]


def make_synthetic_depth_case(
    seed: int = 0,
    height: int = 64,
    width: int = 64,
    num_objects: int = 5,
    noise_std_m: float = 0.05,
) -> SyntheticDepthCase:
    """Builds a synthetic depth case: `num_objects` non-overlapping
    rectangular "objects" at random depths, plus a "predicted" depth map
    equal to ground truth plus Gaussian noise (`noise_std_m`) -- models
    a depth source with known, bounded per-pixel error, distinct from
    the unrelated "relative scale" problem `align_scale` handles for a
    real Depth Anything prediction.

    Args:
        seed: Random seed -- same seed always produces the same case.
        height, width: Depth map dimensions, pixels.
        num_objects: Number of synthetic rectangular objects to place.
        noise_std_m: Standard deviation of the per-pixel noise added to
            produce `predicted_depth` from `ground_truth_depth`.

    Returns:
        A `SyntheticDepthCase`.
    """

    rng = np.random.default_rng(seed)

    ground_truth = np.full((height, width), 5.0, dtype=float)  # background depth
    detections: List[Detection] = []

    grid = max(1, int(num_objects**0.5) + 1)
    cell_h, cell_w = height // grid, width // grid

    for i in range(num_objects):
        row, col = divmod(i, grid)
        y1 = row * cell_h + 2
        x1 = col * cell_w + 2
        y2 = min(height, y1 + cell_h - 4)
        x2 = min(width, x1 + cell_w - 4)

        if y2 <= y1 or x2 <= x1:
            continue

        object_depth = float(rng.uniform(0.5, 3.0))
        ground_truth[y1:y2, x1:x2] = object_depth

        detections.append(
            Detection(
                label="object",
                confidence=0.9,
                bbox=[float(x1), float(y1), float(x2), float(y2)],
            )
        )

    noise = rng.normal(loc=0.0, scale=noise_std_m, size=ground_truth.shape)
    predicted = np.clip(ground_truth + noise, a_min=0.01, a_max=None)

    return SyntheticDepthCase(
        ground_truth_depth=ground_truth,
        predicted_depth=predicted,
        detections=detections,
    )


def make_synthetic_tracking_sequence(
    seed: int = 0,
    num_objects: int = 4,
    num_frames: int = 20,
    occlusion_probability: float = 0.15,
) -> List[List[Detection]]:
    """Builds a sequence of frames, each a list of `Detection`s (no
    `tracking_id` set -- that's `IoUTracker`'s job when this sequence is
    run through it), simulating objects that drift slightly each frame
    and occasionally go missing (occlusion).

    Each returned `Detection` carries its originating synthetic object's
    identity in `detection.attributes["ground_truth_id"]` -- the
    benchmark's ground truth, never touched by `IoUTracker` (which only
    reads `label`/`bbox`/`position_3d`), so comparing
    `detection.tracking_id` (assigned by the tracker) against
    `detection.attributes["ground_truth_id"]` (known up front) after
    running the tracker is a direct, unambiguous correctness check.

    Args:
        seed: Random seed.
        num_objects: Number of distinct synthetic objects.
        num_frames: Number of frames to generate.
        occlusion_probability: Per-object, per-frame probability the
            object is omitted from that frame entirely (simulating
            occlusion -- see the project's "Object Permanence" tests).

    Returns:
        `num_frames` lists of `Detection`, in frame order.
    """

    rng = random.Random(seed)

    starting_positions = [
        (20.0 * i, 20.0 * i, 20.0 * i + 15.0, 20.0 * i + 15.0)
        for i in range(num_objects)
    ]

    frames: List[List[Detection]] = []
    positions = list(starting_positions)

    for _frame_index in range(num_frames):
        frame: List[Detection] = []

        for gt_id in range(num_objects):
            if rng.random() < occlusion_probability:
                continue  # occluded this frame

            x1, y1, x2, y2 = positions[gt_id]
            dx, dy = rng.uniform(-1.0, 1.0), rng.uniform(-1.0, 1.0)
            x1, y1, x2, y2 = x1 + dx, y1 + dy, x2 + dx, y2 + dy
            positions[gt_id] = (x1, y1, x2, y2)

            detection = Detection(label="object", confidence=0.9, bbox=[x1, y1, x2, y2])
            detection.attributes["ground_truth_id"] = gt_id
            frame.append(detection)

        frames.append(frame)

    return frames

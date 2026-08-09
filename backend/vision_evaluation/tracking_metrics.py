"""
tracking_metrics.py

Purpose
-------
Tracking quality metrics computed over a sequence of per-frame
ground-truth-id -> predicted-id correspondences. Matching a predicted
detection to a ground-truth object (by 3D proximity, bbox IoU, or a
synthetic dataset's known 1:1 correspondence) is the *caller's*
responsibility (`benchmark_runner.py` does this for the synthetic
cases in this package); this module only computes metrics from
already-matched correspondences, so the metric math stays independently
testable and does not silently re-implement matching logic that already
has one owner (`vision/tracking/iou_tracker.py`).

Metric definitions
-------------------------
- ID switches: a "switch" is counted every time a ground-truth object
  that was visible in the previous frame is visible again this frame
  with a *different* non-None predicted id than it had last time it was
  seen. Units: count. Interpretation: lower is better; each switch is a
  point where the planner would (incorrectly) treat a continuously
  visible object as a new one.
- Track fragmentation: for each ground-truth object, the number of
  contiguous predicted-id "segments" covering its visible frames, minus
  1 (a perfectly tracked object has exactly one segment ->
  fragmentation 0). Units: count, summed across all ground-truth
  objects. Interpretation: lower is better; distinct from ID switches
  in that a single missed frame with no re-detection at all (a `None`
  predicted id) still fragments the track even without ever assigning
  a *wrong* id.
- Recall: `matched predictions / total ground-truth appearances`.
  Unitless (a fraction). Interpretation: of every frame a ground-truth
  object was actually visible, what fraction did the tracker assign
  any id to at all.
- Tracking success rate: fraction of ground-truth objects tracked with
  a single, unbroken, correct predicted id for their *entire* visible
  span (fragmentation == 0 and zero ID switches for that object).
  Unitless (a fraction). Interpretation: the strictest per-object
  metric -- an object counts only if its identity was never lost or
  confused, matching the project's "persistent identity" goal directly.

Why no "precision" metric
------------------------------
A precision metric (fraction of predicted ids that correspond to a real
object) requires being able to represent a false-positive prediction --
an id assigned to something that was not a real ground-truth object at
all. This module's input shape (`{ground_truth_id: predicted_id}` per
frame) is keyed by ground-truth id by construction, so every predicted
id it sees is already known to correspond to a real object; there is no
way to express "the tracker invented a track" in this shape. Reporting
a precision metric here would always trivially equal 1.0 and would
misrepresent measured behavior as a real result -- omitted rather than
faked.

Why not MOTA/MOTP
----------------------
MOTA/MOTP are standard multi-object-tracking metrics from the
video-tracking literature, but they're built around per-frame
spatial-overlap matching against a labeled video dataset with known
object counts per frame -- infrastructure this project does not have
(no labeled AI2-THOR tracking dataset exists; see this package's
`__init__.py`). Introducing them here would be "implementing metrics
because they are common in papers" without the data to make them
meaningful, which the project spec explicitly warns against. The
metrics above were chosen because they can be computed correctly from
what this project's synthetic harness (and, if this framework is later
pointed at a real logged sequence, a real one) actually has: matched
per-frame id correspondences.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from vision_evaluation.models import MetricValue


def _metric(
    name: str,
    definition: str,
    units: str,
    numerator: float,
    denominator: float,
    interpretation: str,
) -> MetricValue:
    return MetricValue(
        name=name,
        definition=definition,
        units=units,
        numerator=float(numerator),
        denominator=float(denominator),
        interpretation=interpretation,
    )


def compute_tracking_metrics(
    frames: List[Dict[int, Optional[int]]],
) -> Dict[str, MetricValue]:
    """Computes tracking metrics from a sequence of per-frame correspondences.

    Args:
        frames: One dict per frame, `{ground_truth_id: predicted_id}`.
            Every ground-truth object visible in that frame must have an
            entry; `predicted_id=None` means the tracker did not assign
            any id to it that frame (missed detection). A ground-truth
            id absent from a frame's dict means that object was not
            visible in that frame at all (not the same as `None`).

    Returns:
        `{"id_switches", "track_fragmentation", "recall",
        "tracking_success_rate"}` mapped to `MetricValue`s (no
        "precision" -- see module docstring for why).
    """

    # Per-ground-truth-id history: list of (frame_index, predicted_id)
    # for every frame that object was visible in, in frame order.
    histories: Dict[int, List[Optional[int]]] = {}
    for frame in frames:
        for gt_id, predicted_id in frame.items():
            histories.setdefault(gt_id, []).append(predicted_id)

    id_switches = 0
    fragmentation_total = 0
    fully_correct_objects = 0

    matched_predictions = 0
    total_ground_truth_appearances = 0

    for gt_id, predicted_sequence in histories.items():
        total_ground_truth_appearances += len(predicted_sequence)
        matched_predictions += sum(1 for p in predicted_sequence if p is not None)

        # Segments: count transitions where the predicted id changes
        # (including into/out of None) -- number of segments is
        # (transitions + 1); fragmentation is segments - 1.
        transitions = sum(
            1
            for prev, curr in zip(predicted_sequence, predicted_sequence[1:])
            if prev != curr
        )
        fragmentation_total += transitions

        # ID switches: consecutive non-None predicted ids that differ.
        switches_for_object = sum(
            1
            for prev, curr in zip(predicted_sequence, predicted_sequence[1:])
            if prev is not None and curr is not None and prev != curr
        )
        id_switches += switches_for_object

        if transitions == 0 and None not in predicted_sequence:
            fully_correct_objects += 1

    num_objects = len(histories)

    return {
        "id_switches": _metric(
            "id_switches",
            "Count of frames where a continuously visible ground-truth "
            "object's predicted id changed from a non-None previous value.",
            "count",
            id_switches,
            1,
            "Lower is better; each switch is a point where the same "
            "physical object would appear to the planner as a new one.",
        ),
        "track_fragmentation": _metric(
            "track_fragmentation",
            "Sum over ground-truth objects of (number of contiguous "
            "predicted-id segments - 1).",
            "count",
            fragmentation_total,
            1,
            "Lower is better; captures identity breaks including missed "
            "detections (None), not just wrong-id switches.",
        ),
        "recall": _metric(
            "recall",
            "Frames with a non-None predicted id divided by total "
            "ground-truth appearances.",
            "unitless (fraction)",
            matched_predictions,
            total_ground_truth_appearances,
            "Higher is better; how often the tracker identified an object "
            "that was actually visible.",
        ),
        "tracking_success_rate": _metric(
            "tracking_success_rate",
            "Fraction of ground-truth objects tracked with a single, "
            "unbroken predicted id for their entire visible span.",
            "unitless (fraction)",
            fully_correct_objects,
            num_objects,
            "Higher is better; the strictest per-object identity metric.",
        ),
    }

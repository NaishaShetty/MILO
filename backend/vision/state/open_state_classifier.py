"""
open_state_classifier.py

Purpose
-------
Determines whether a detected container (fridge, cabinet, microwave,
...) currently *appears* open or closed, from vision -- not AI2-THOR's
symbolic `isOpen` metadata. Fills in `Detection.attributes["is_open"]`
(`True`/`False`/`None`), which `planner.grounding.ground_world_state()`
then reads to ground `ObjectState.is_open` -- see that module's
docstring for the vision-vs-symbolic reconciliation policy.

Why this reuses `GroundingDINODetector`'s model, not a new one
------------------------------------------------------------------
Grounding DINO is a *phrase-grounded* detector: given free-text
phrases, it scores how well each matches image content. That is
already exactly the tool needed here -- "open" vs "closed" are just
two more phrases, no different in kind from "chair" or "table". Using
the same already-loaded model/processor `GroundingDINODetector`
constructs means this classifier costs one extra small forward pass
per classified detection, no new weights, no new dependency, and no
second multi-gigabyte model to keep resident in the 6GB VRAM budget
documented in `docs/roadmap.md`'s CPU-bound-vision-inference entry.

Why per-detection crops, not one whole-frame prompt
-----------------------------------------------------
Grounding DINO's box output for "open"/"closed" against the *whole*
frame has no reliable way to associate a returned box with a specific
already-detected object -- two different fridges (or a fridge and a
cabinet) in frame would produce ambiguous, unassociated open/closed
boxes. Cropping to each `Detection.bbox` first (with a small margin,
so the crop still shows the object's edges/hinge, not just its
interior) turns "is *this* object open" into a simple two-phrase
classification over a single-object image, with no association
problem.

Limitations -- read before trusting a `True`/`False` result
----------------------------------------------------------------
This is a real, measured vision signal, not a certified appearance
model: `docs/architecture/spatial_perception.md`'s "no appearance
model" limitation (originally about `planner.grounding.
ground_world_state()`'s scope) still applies to *this* classifier's
own accuracy, just not to whether the *attempt* is real. Concretely:
- A container mostly out of frame, at a bad angle, or too small in the
  crop can produce two low, inconclusive scores -- returned as `None`
  ("don't know"), never guessed.
- **Real smoke test against a live AI2-THOR fridge**
  (`test_open_state_classifier.py`, run manually): 2/3 correct --
  closed correctly classified `False` both times (before and after
  re-closing), but the open case was missed (`False` instead of
  `True`; the base detector's own phrase match also shifted from
  "fridge" to "door" once the door swung open, a separate,
  compounding effect). A wider crop margin (60px) was tried and made
  this *worse* (all three frames returned `None`) -- more surrounding
  context apparently diluted the signal rather than helping, so the
  smaller default margin (20px) was kept. This is a real, small,
  reported result, not a claim of solved accuracy -- a proper
  labeled-scene benchmark (matching `milo_benchmark`'s tier1_locate
  perception check's own path from "wired up" to "measured") is
  future work, tracked in `docs/roadmap.md`.
"""

from __future__ import annotations

from typing import Optional

import torch

from scene.detection import Detection
from scene.scene import Scene
from vision.detectors.grounding_dino_detector import GroundingDINODetector

#: Crop margin (pixels) added around `Detection.bbox` before
#: classification, so the open/closed decision sees a bit of the
#: object's surroundings (hinge, door swing) rather than a tight crop
#: that could clip the very evidence that distinguishes open/closed.
CROP_MARGIN_PX = 20

#: Lower than `GroundingDINODetector`'s production
#: `box_threshold=0.25`/`text_threshold=0.25` (see that class's
#: default args -- validated via `planning_evaluation/
#: validate_detection_threshold.py`, see `docs/roadmap.md`): this
#: classifier scores exactly two candidate phrases against a small,
#: single-object crop, a much easier decision than open-vocabulary
#: detection across a whole cluttered scene, so a lower confidence
#: bar is appropriate here. Configurable, not hardcoded past this
#: module boundary, so a future calibration pass (once real
#: open/closed accuracy is measured with its own validation set, the
#: same way the main detector's threshold now is) can adjust it
#: without touching call sites.
CLASSIFICATION_THRESHOLD = 0.2

#: The two phrases classified against each crop. Order matters only
#: for readability; `classify_open_state` reads scores by label text,
#: not position.
_OPEN_CLOSED_PROMPT = "open. closed."


class OpenStateClassifier:
    """Vision-grounded open/closed classifier for detected containers.

    Wraps an existing, already-loaded `GroundingDINODetector` (no
    separate model/weights of its own -- see module docstring) to
    answer "does this specific detection currently look open or
    closed" per `Detection`, writing the result to
    `Detection.attributes["is_open"]`.
    """

    def __init__(self, detector: GroundingDINODetector):
        """
        Args:
            detector: An already-constructed `GroundingDINODetector`
                (e.g. the same one a `VisionAgent`'s pipeline uses) --
                its loaded `processor`/`model` are reused directly, so
                no second Grounding DINO instance is ever created.
        """
        self.detector = detector

    def classify(self, image, detection: Detection) -> Optional[bool]:
        """Classifies one detection's crop as open (`True`), closed
        (`False`), or unknown (`None`).

        Args:
            image: The RGB `numpy.ndarray` `detection` was produced
                from (same frame `detection.bbox` is relative to).
            detection: The `Detection` to classify. Not mutated by
                this method -- see `process()` for the mutating,
                `Scene`-level entry point.

        Returns:
            `True` if "open" scores higher than "closed" and clears
            `CLASSIFICATION_THRESHOLD`; `False` for the reverse;
            `None` if neither phrase clears the threshold (the crop
            gives no confident evidence either way).
        """
        height, width = image.shape[:2]
        x1, y1, x2, y2 = detection.bbox
        x1 = max(0, int(x1) - CROP_MARGIN_PX)
        y1 = max(0, int(y1) - CROP_MARGIN_PX)
        x2 = min(width, int(x2) + CROP_MARGIN_PX)
        y2 = min(height, int(y2) + CROP_MARGIN_PX)
        if x2 <= x1 or y2 <= y1:
            return None

        crop = image[y1:y2, x1:x2]
        processor = self.detector.processor
        model = self.detector.model
        device = self.detector.device

        inputs = processor(
            images=crop, text=_OPEN_CLOSED_PROMPT, return_tensors="pt"
        ).to(device)

        with torch.no_grad():
            outputs = model(**inputs)

        results = processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            threshold=CLASSIFICATION_THRESHOLD,
            text_threshold=CLASSIFICATION_THRESHOLD,
            target_sizes=[crop.shape[:2]],
        )[0]

        open_score = 0.0
        closed_score = 0.0
        for score, label in zip(results["scores"], results["text_labels"]):
            normalized = label.strip().lower()
            score = float(score)
            if normalized == "open":
                open_score = max(open_score, score)
            elif normalized == "closed":
                closed_score = max(closed_score, score)

        if open_score == 0.0 and closed_score == 0.0:
            return None
        return open_score > closed_score

    def process(self, image, scene: Scene, *, labels: Optional[set] = None) -> Scene:
        """Classifies every eligible detection in `scene` and writes
        `detection.attributes["is_open"]` in place.

        Args:
            image: The RGB `numpy.ndarray` `scene`'s detections were
                produced from.
            scene: The `Scene` to enrich in place.
            labels: Optional set of lowercase labels to restrict
                classification to (e.g. known container types). `None`
                (default) classifies every detection -- harmless but
                wasteful for obviously non-openable objects (a "mug"),
                so callers that know their container vocabulary should
                pass it.

        Returns:
            The same `scene`, with `detection.attributes["is_open"]`
            set (`True`/`False`/`None`) on every classified detection.
        """
        for detection in scene.detections:
            if labels is not None and detection.label.strip().lower() not in labels:
                continue
            detection.attributes["is_open"] = self.classify(image, detection)
        return scene

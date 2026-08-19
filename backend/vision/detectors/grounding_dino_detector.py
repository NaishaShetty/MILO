"""
grounding_dino_detector.py

Purpose
-------
Runs the Grounding DINO vision-language object detector.

Responsibilities
-----------------
- Implement `BaseDetector` for the Grounding DINO model specifically.
- Build model inputs from an RGB image and a text prompt, run a
  forward pass, and add the resulting detections to the `Scene`
  passed into `process`.

Why this abstraction exists
-----------------------------
This class owns exactly the Grounding DINO *inference* logic. It
deliberately does NOT know where the model's weights come from or how
they get onto disk -- that responsibility belongs to
`config.model_config` (what/where) and `config.model_manager`
(download/load), so this file never hardcodes a model name or a
filesystem path. Swapping Grounding DINO for a different checkpoint,
or changing where models are cached, never requires touching this
file.

It lives in `vision/detectors/` rather than directly under `vision/`
so that as more detectors are added (a fine-tuned model, a different
zero-shot detector, ...) they all sit in one place, distinct from
segmentation (`vision/segmenters`), depth (`vision/depth`), and
tracking (`vision/tracking`).
"""

import torch
from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

from config.model_config import GROUNDING_DINO, get_device
from config.model_manager import ModelManager
from scene.detection import Detection
from scene.metadata_keys import SceneMetadata
from vision.detectors.base_detector import BaseDetector


class GroundingDINODetector(BaseDetector):
    """
    Wrapper around the Grounding DINO model.
    """

    def __init__(self, box_threshold=0.25, text_threshold=0.25):

        self.device = get_device()

        # Detection thresholds are construction-time configuration
        # rather than `process()` arguments, so that `process(image,
        # scene)` keeps the same two-argument shape as every other
        # perception module (segmenter, depth estimator, tracker).
        #
        # box_threshold was 0.35 before -- lowered to 0.25 after a
        # real precision/recall validation across 8 scenes, 9 true
        # positives (ground-truth-visible objects), 14 true negatives
        # (confirmed-absent objects): 0.25 had the same recall as 0.15
        # (77.8%) with meaningfully better precision (63.6% vs 53.8%),
        # AND both equal-or-better recall (77.8% vs 55.6%) and
        # equal-or-better precision (63.6% vs 62.5%) than the old 0.35
        # -- it dominates both previously-considered values on real
        # data, not just recall in isolation. This is what the
        # sim-to-real detection-confidence gap's original finding
        # explicitly deferred ("its effect on false-positive rate...
        # was never measured, so shipping it would trade one
        # unmeasured risk for another") -- now measured. See
        # `planning_evaluation/validate_detection_threshold.py` and
        # `docs/roadmap.md`.
        self.box_threshold = box_threshold
        self.text_threshold = text_threshold

        print("Loading Grounding DINO...")
        print("Using device:", self.device)

        manager = ModelManager(GROUNDING_DINO)
        self.processor, self.model = manager.load(
            AutoProcessor,
            AutoModelForZeroShotObjectDetection,
            device=self.device,
        )

        print("Grounding DINO loaded successfully.")

    def process(self, image, scene):
        """
        Runs Grounding DINO on an RGB image and adds the resulting
        detections to `scene`.

        Parameters
        ----------
        image:
            RGB numpy array.

        scene:
            The `Scene` being built for this frame. The text prompt
            (e.g. "chair. table. mug. refrigerator.") is read from
            `scene.metadata[SceneMetadata.DETECTION_PROMPT]`.

        Returns
        -------
        The same `Scene`, with detections added.
        """

        prompt = scene.metadata.get(SceneMetadata.DETECTION_PROMPT)

        if not prompt:
            raise ValueError(
                "GroundingDINODetector.process requires "
                "scene.metadata[SceneMetadata.DETECTION_PROMPT] to be set."
            )

        inputs = self.processor(images=image, text=prompt, return_tensors="pt").to(
            self.device
        )

        with torch.no_grad():

            outputs = self.model(**inputs)

        results = self.processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            threshold=self.box_threshold,
            text_threshold=self.text_threshold,
            target_sizes=[image.shape[:2]],
        )[0]

        for score, label, box in zip(
            results["scores"], results["text_labels"], results["boxes"]
        ):

            scene.add_detection(
                Detection(label=label, confidence=float(score), bbox=box.tolist())
            )

        return scene

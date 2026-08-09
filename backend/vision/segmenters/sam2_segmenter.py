"""
sam2_segmenter.py

Purpose
-------
Runs SAM2 to turn each Grounding DINO bounding box already present in
a Scene into a pixel-accurate mask.

Responsibilities
-----------------
- Implement `BaseSegmenter`: enrich an existing `Scene`'s detections
  with masks, never create new detections.
- For every `Detection` in the scene, use its `bbox` as a box prompt
  for SAM2, run a forward pass, and attach the resulting `Mask`
  (scene/mask.py) to that detection.

Pipeline per detection
------------------------
Detection.bbox -> SAM2 box prompt -> SAM2 forward pass -> binary mask
-> Mask(binary, area, bbox) -> Detection.mask

Why this abstraction exists
-----------------------------
Same reasoning as `GroundingDINODetector`: this class owns exactly the
SAM2 *inference* logic and knows nothing about where its weights come
from (`config.model_config` / `config.model_manager` own that). It
implements `process(image, scene)` -- not `detect(image, prompt)` --
because a segmenter doesn't detect objects on its own; it depends on
detections already present in `scene` (see `base_segmenter.py`).

Checkpoint note
----------------
`SAM2` in `config/model_config.py` intentionally does NOT point at the
official `facebook/sam2-hiera-base-plus-hf` repo -- that repo's
weights use parameter names (`image_encoder.*`, `sam_mask_decoder.*`)
that don't match any version of `transformers`' `Sam2Model` and load
as silently random weights. See the comment on `SAM2` in
`model_config.py` for the verification and the (community) checkpoint
used instead.

"model_type" warning note
----------------------------
Loading logs `"You are using a model of type sam2_video to
instantiate a model of type sam2."`. This is a config-labeling quirk
of every SAM2.1 checkpoint currently on the Hub -- confirmed by
inspecting `facebook/sam2.1-hiera-tiny` (the official repo) itself,
which ships the exact same `"model_type": "sam2_video"` /
`"architectures": ["Sam2VideoModel"]` in its `config.json`, and by
`transformers`' own `Sam2Config` docstring, which states its defaults
mirror that same repo. It is not specific to the `danelcsb` mirror
used here, and not a sign of a stale or misconfigured local checkpoint.

It is also verified harmless for this checkpoint: loading with
`output_loading_info=True` reports zero missing, unexpected, or
mismatched keys against `Sam2Model` -- i.e. the video-typed config
carries an image encoder / prompt encoder / mask decoder whose
parameter names and shapes are a perfect match for `Sam2Model`, the
warning is just `transformers` flagging that the config's declared
`model_type` string doesn't equal `Sam2Model.model_type`. Given that,
the warning is suppressed for the duration of this one `load()` call
via the `transformers.configuration_utils` logger rather than left to
print on every run.
"""

import logging

import torch
from PIL import Image
from transformers import Sam2Model, Sam2Processor

from config.model_config import SAM2, get_device
from config.model_manager import ModelManager
from scene.mask import Mask
from vision.segmenters.base_segmenter import BaseSegmenter


class SAM2Segmenter(BaseSegmenter):
    """
    Wrapper around the SAM2 model, prompted with existing detection
    boxes.
    """

    def __init__(self):

        self.device = get_device()

        print("Loading SAM2...")
        print("Using device:", self.device)

        manager = ModelManager(SAM2)

        # See "model_type" warning note above: every SAM2.1 checkpoint
        # on the Hub (including the official facebook repo) declares
        # model_type "sam2_video", which transformers flags as a
        # mismatch against Sam2Model.model_type ("sam2") even though
        # the weights load with zero missing/unexpected/mismatched
        # keys. Scoped to just this call so unrelated warnings from
        # other models (Grounding DINO, future depth/tracking models)
        # are never silenced by it.
        config_logger = logging.getLogger("transformers.configuration_utils")
        previous_level = config_logger.level
        config_logger.setLevel(logging.ERROR)
        try:
            self.processor, self.model = manager.load(
                Sam2Processor,
                Sam2Model,
                device=self.device,
            )
        finally:
            config_logger.setLevel(previous_level)

        print("SAM2 loaded successfully.")

    def process(self, image, scene):
        """
        Segments every existing detection in `scene`.

        Parameters
        ----------
        image:
            RGB numpy array -- the same frame the detections in
            `scene` were produced from.

        scene:
            The `Scene` being built for this frame. Each
            `scene.detections[i].bbox` is used as a SAM2 box prompt.
            Detections are re-segmented unconditionally (no skip
            logic), matching a detector's stateless-per-call
            behavior.

        Returns
        -------
        The same `Scene`, with `mask` set on every detection.
        """

        if not scene.detections:
            return scene

        pil_image = Image.fromarray(image)

        for detection in scene.detections:

            box = detection.bbox

            inputs = self.processor(
                images=pil_image,
                input_boxes=[[box]],
                return_tensors="pt",
            ).to(self.device)

            with torch.no_grad():

                outputs = self.model(**inputs, multimask_output=False)

            masks = self.processor.post_process_masks(
                outputs.pred_masks,
                inputs["original_sizes"],
            )

            # masks[0]: this image's masks, shaped
            # [num_prompts, num_masks_per_prompt, H, W]. One box
            # prompt and multimask_output=False means both of those
            # dims are 1.
            binary_mask = masks[0][0, 0].cpu().numpy().astype(bool)

            detection.mask = Mask(
                binary=binary_mask,
                area=int(binary_mask.sum()),
                bbox=box,
            )

        return scene

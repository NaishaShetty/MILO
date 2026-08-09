"""
vision/segmenters

Purpose
-------
Home for pixel-level segmentation models (e.g. SAM2). Kept as a
sibling of `vision/detectors` rather than nested inside it, since
segmentation is a distinct capability from box-level detection -- a
segmenter typically consumes a detector's output (a box or point
prompt) rather than replacing it.

`SAM2Segmenter` (sam2_segmenter.py) implements `BaseSegmenter`
(base_segmenter.py) for SAM2 specifically, taking existing
`Detection.bbox` boxes as prompts and attaching `Mask`s. Sibling
segmenters (a future point-prompted or automatic-mask-generation
model) belong here too.
"""

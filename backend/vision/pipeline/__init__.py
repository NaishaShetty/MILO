"""
vision/pipeline

Purpose
-------
Home for `PerceptionPipeline`, the object that owns perception-stage
sequencing (detector -> segmenter -> depth -> tracker -> scene graph)
so that `VisionAgent` doesn't have to.

See `perception_pipeline.py` for the full rationale.
"""

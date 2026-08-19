"""
vision/state

Purpose
-------
Home for vision-grounded *object state* signals -- properties beyond
"what is it and where" (existence/location, already handled by
`vision/detectors`+`vision/segmenters`+`planner/grounding.py`) that
still come from looking at the current frame rather than from
AI2-THOR's own symbolic metadata: whether a container currently
appears open or closed (`open_state_classifier.py`), and (via
`planner.grounding.ground_world_state()`'s held-object heuristic)
which object the agent appears to be holding.

Why a separate package, not another `vision/detectors` stage
--------------------------------------------------------------
`vision.pipeline.PerceptionPipeline.__init__`'s stage list is frozen
(see `docs/architecture/api_contracts.md` and
`docs/architecture/spatial_perception.md`'s "Why localization is not a
6th pipeline stage" note) -- a state classifier is deliberately an
*optional, explicitly-invoked* extra step a caller runs on an already
-built `Scene`, not a permanent stage every `VisionAgent.perceive()`
call pays for, the same precedent `localization.py` already set for
"real signal, but not everyone needs it every frame."
"""

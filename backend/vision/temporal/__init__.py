"""
vision/temporal

Purpose
-------
Home for Phase 3.x.6's Temporal Scene Representation: turning a sequence
of single-frame `Scene`s (each already carrying stable `tracking_id`s
from `vision/tracking/`) into "what changed since last time" --- new,
removed, moved, occluded, reappeared objects.

Why this is separate from `vision/tracking`
-----------------------------------------------
Tracking answers "is this the same object I saw before" (per-detection
identity, one frame at a time). Temporal scene representation answers a
different question one level up: "given identity is already resolved,
what changed between two whole scenes." Keeping them in separate
modules means a future caller can consume tracked `Scene`s without
temporal diffing (e.g. a single-frame API response) or temporal diffing
without needing to know how identity was resolved (it only reads
`Detection.tracking_id`, already set by whatever tracker ran).

See `scene_diff.py` for the pure comparison function and
`temporal_scene.py` for the stateful orchestrator built on top of it --
including the memory-boundary note on why this stays short-term/
in-process only (not a long-term Memory system).
"""

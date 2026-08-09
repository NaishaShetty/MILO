"""
relationship.py

Purpose
-------
Defines the `Relationship` data model: one inferred spatial or
semantic connection between two detections in a `Scene`, plus the
`RelationshipType` predicate vocabulary used to label it.

Why it exists
-------------
Phase 2.8 (Scene Graph Generation) turns a flat list of detections
into a graph -- objects as nodes, relationships as edges -- so that
downstream reasoning ("is the mug on the table?", "is the apple inside
the refrigerator?") doesn't have to be re-derived from raw bounding
boxes every time something needs it. `Scene.relationships` was already
reserved as a placeholder field (see `scene/scene.py`) for exactly this;
this file is what gives that field a concrete, typed element instead of
`Any`.

Where it fits in the overall architecture
-------------------------------------------
`Relationship` is produced by scene-graph stages
(`vision/scene_graph/base_scene_graph.py` and its implementations)
during `PerceptionPipeline` execution, the same way `Detection` is
produced by detectors and `Mask` by segmenters. It is pure data --
this file runs no reasoning itself -- so any future consumer (planner,
memory, a natural-language scene description generator) can depend on
`Relationship` without depending on how it was inferred (heuristic
bounding-box geometry today, a learned relationship classifier later).

Which future modules will depend on this
--------------------------------------------
- Every `BaseSceneGraph` implementation (heuristic today, learned
  models later) constructs `Relationship` instances and appends them
  to `scene.relationships`.
- The future language-driven planner will read `scene.relationships`
  to resolve references like "the mug on the table" to specific
  detections.
- A future natural-language scene description module could walk
  `scene.relationships` to generate captions/summaries.

Why `subject_id`/`object_id` are plain integers
----------------------------------------------------
`Detection` has no persistent identity field populated yet --
`tracking_id` (see `scene/detection.py`) is reserved for a future
tracker and is `None` until one exists. Until then, the only stable
way to refer to "which detection" within a single `Scene` is its index
into `scene.detections`. `subject_id`/`object_id` are therefore that
index (an `int`), not a `Detection` reference or a `tracking_id`. Once
a tracker populates `tracking_id`, a scene-graph implementation may
choose to use that instead for relationships that need to stay stable
across frames -- this dataclass does not need to change for that,
since both are already typed as plain `int`.

Who is allowed to depend on this file
-----------------------------------------
As of the Phase 2 API freeze (see
`docs/architecture/api_contracts.md`), `Relationship`'s field schema
is a frozen public interface. Every future module -- Language,
Planner, Memory, Execution, Frontend -- reading `Scene.relationships`
should rely on this field set rather than on which `BaseSceneGraph`
implementation produced it. `RelationshipType`'s existing constants
are similarly stable; new predicates may be added by future
implementations without breaking this contract.
"""

from dataclasses import dataclass, field
from typing import Any, Dict


class RelationshipType:
    """Canonical predicate names a `BaseSceneGraph` may assign.

    Mirrors the pattern used by `scene.metadata_keys.SceneMetadata`:
    centralizing well-known string constants so callers get
    autocomplete and typo-checking instead of raw strings like
    `"LEFT_OFF"` failing silently. This is not a closed enum -- a
    future learned scene-graph model may produce predicates not listed
    here (e.g. `"ON"`, `"HOLDING"`) -- but every predicate the
    heuristic implementation in this project currently produces is
    listed below.

    Attributes:
        LEFT_OF: Subject's bounding-box center is to the left of the
            object's, with no overlap.
        RIGHT_OF: Subject's bounding-box center is to the right of the
            object's, with no overlap.
        ABOVE: Subject's bounding-box center is above the object's,
            with no overlap.
        BELOW: Subject's bounding-box center is below the object's,
            with no overlap.
        INTERSECTS: Subject and object overlap, but below the
            `OVERLAPS` containment/IoU thresholds.
        INSIDE: Subject is almost entirely contained within the
            object.
        OVERLAPS: Subject and object share substantial area (IoU above
            threshold) without one containing the other.
        NEAR: Subject and object are close in 3D space (below a
            configured distance threshold), regardless of whether their
            2D projections overlap. Phase 3.x -- only emitted when both
            detections have `position_3d` (i.e. a depth stage ran); see
            `vision/scene_graph/heuristic_scene_graph.py`. Deliberately
            NOT a replacement for the 2D predicates above -- two
            detections can be simultaneously e.g. `LEFT_OF` (2D) and
            `NEAR` (3D); each captures information the other cannot
            (2D says nothing about depth separation, 3D distance alone
            says nothing about left/right).
    """

    LEFT_OF = "LEFT_OF"
    RIGHT_OF = "RIGHT_OF"
    ABOVE = "ABOVE"
    BELOW = "BELOW"

    INTERSECTS = "INTERSECTS"
    INSIDE = "INSIDE"
    OVERLAPS = "OVERLAPS"

    NEAR = "NEAR"


# --------------------------------------------------------------------
# Public API (Frozen after Phase 2)
#
# Language
# Planner
# Memory
# Execution
# Frontend
#
# depend on this interface.
#
# Avoid breaking changes unless absolutely necessary.
# --------------------------------------------------------------------
@dataclass
class Relationship:
    """One directed edge in a scene graph.

    `subject_id` stands in `predicate` relation to `object_id`, e.g.
    `Relationship(subject_id=0, predicate=RelationshipType.INSIDE,
    object_id=2, confidence=0.95)` reads as "detection 0 is inside
    detection 2".

    Attributes:
        subject_id: Index into `Scene.detections` for the relation's
            subject.
        predicate: A `RelationshipType` constant (or another
            implementation-defined string) naming the relation.
        object_id: Index into `Scene.detections` for the relation's
            object.
        confidence: Confidence in `[0, 1]` that this relationship
            holds. Defaults to `1.0` for deterministic
            (non-probabilistic) inference methods.
        metadata: Open-ended bag for implementation-specific evidence
            (e.g. IoU, pixel intersection area) supporting this
            relationship.
    """

    subject_id: int
    predicate: str
    object_id: int

    confidence: float = 1.0

    metadata: Dict[str, Any] = field(default_factory=dict)

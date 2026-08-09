"""
heuristic_scene_graph.py

Purpose
-------
Infers spatial relationships between a `Scene`'s existing detections
using bounding-box and mask geometry alone -- no learned model.

Why it exists
-------------
A scene-graph stage needs to exist before a learned one can be
trained, benchmarked, or even usefully compared against -- something
has to populate `Scene.relationships` first, and something has to
serve as the baseline a future learned model is measured against.
Pure geometric reasoning (is this box to the left of that one? does
this mask fall inside that one?) requires no training data and no
model weights, so it's the natural first implementation.

Where it fits in the overall architecture
-------------------------------------------
Implements `BaseSceneGraph` (`base_scene_graph.py`): a
`PerceptionPipeline` stage that reads `scene.detections` (their
`bbox`, and `mask` when a segmenter ran first) and appends
`Relationship` objects to `scene.relationships`. It runs after
detection and segmentation, never before -- it has nothing to reason
about until objects (and ideally their masks) already exist in
`scene`.

Which future modules will depend on this
--------------------------------------------
- `PerceptionPipeline`, via its `scene_graph=` constructor keyword.
- The future language-driven planner, which reads `scene.relationships`
  to disambiguate object references.
- A future learned scene-graph model, which this class's predicate
  vocabulary (`RelationshipType`) and output shape (`Relationship`)
  are shared with, so the planner does not need to change when the
  scene-graph implementation does.

Algorithm
---------
For every unordered pair of detections `(a, b)`:

1. Compute their overlap. If both have a `Mask`, overlap is the exact
   pixel intersection of `mask.binary`; otherwise it falls back to the
   bounding-box intersection area. Mask-based overlap is preferred
   because two bounding boxes can overlap heavily while the actual
   objects (and their masks) do not -- e.g. two objects side by side
   with boxes that touch near a corner.
2. If one detection's area is almost entirely (>= `INSIDE_THRESHOLD`)
   contained within the other's overlap area, emit `INSIDE`
   (the contained detection is the subject).
3. Otherwise, if their IoU is at least `OVERLAP_IOU_THRESHOLD`, emit
   `OVERLAPS` (substantial but not containing overlap).
4. Otherwise, if they overlap at all (but below the `OVERLAPS`
   threshold), emit `INTERSECTS` (touching/grazing overlap).
5. Otherwise (no overlap at all), fall back to a purely directional
   relationship from each detection's bounding-box center: whichever
   axis (horizontal vs. vertical) has the larger center-to-center
   displacement determines `LEFT_OF`/`RIGHT_OF` vs. `ABOVE`/`BELOW`.

Exactly one 2D `Relationship` is emitted per pair from the geometry
above, so that part of this stage still produces `N * (N - 1) / 2`
relationships for `N` detections -- unchanged from Phase 2.

Phase 3.x: depth-aware `NEAR` relationships
------------------------------------------------
2D geometry alone cannot tell whether two objects are physically close
in 3D -- a mug in the foreground and a shelf far behind it can share the
exact same screen-space `LEFT_OF` relationship as a mug and shelf that
are actually touching. When both detections in a pair have
`position_3d` set (i.e. a depth stage ran before this one in the
pipeline -- see `perception_pipeline.py`), this stage additionally
checks their 3D Euclidean distance and emits a `NEAR` relationship if
it's within `NEAR_DISTANCE_THRESHOLD_M`. This is emitted *in addition
to*, not instead of, the 2D relationship for that pair -- see
`RelationshipType.NEAR`'s docstring for why both can hold at once. When
no detection has `position_3d` (no depth stage configured), this stage
degrades gracefully to exactly its Phase 2 behavior -- no `NEAR`
relationships are ever fabricated from 2D data alone, since that would
misrepresent GT-adjacent claims a caller might reasonably rely on for
"is this object close enough to grasp."
"""

import math
from itertools import combinations

from scene.relationship import Relationship, RelationshipType
from scene.scene import Scene
from vision.scene_graph.base_scene_graph import BaseSceneGraph

# A detection is considered INSIDE another once this fraction of its
# own area falls within the other's overlap region. Not 1.0, so a
# mask/box that is contained except for a sliver clipped by detector
# noise still counts.
INSIDE_THRESHOLD = 0.9

# Minimum IoU for two non-containing detections to be called OVERLAPS
# rather than the weaker INTERSECTS. Chosen well below 0.5 because
# two distinct real-world objects rarely share more than half their
# projected area even when clearly overlapping in 2D.
OVERLAP_IOU_THRESHOLD = 0.2

# Maximum 3D distance (meters) for two detections to be called NEAR.
# 0.5m is roughly "within arm's reach of each other" for a tabletop/
# household object scale (AI2-THOR's target domain) -- close enough to
# be a meaningful spatial relationship (e.g. "the mug NEAR the plate"),
# not so large that most of a room's objects would trivially qualify.
NEAR_DISTANCE_THRESHOLD_M = 0.5


class HeuristicSceneGraph(BaseSceneGraph):
    """
    Infers `LEFT_OF`/`RIGHT_OF`/`ABOVE`/`BELOW`/`INTERSECTS`/`INSIDE`/
    `OVERLAPS` relationships between every pair of a `Scene`'s
    detections, using only bounding-box and mask geometry.
    """

    def process(self, image, scene: Scene) -> Scene:
        """
        Infers one relationship per pair of `scene.detections` and
        appends the results to `scene.relationships`.

        Parameters
        ----------
        image:
            RGB numpy array. Unused by this purely geometric
            implementation, but part of the shared `process(image,
            scene)` contract every perception stage follows.

        scene:
            The `Scene` whose `detections` (bbox, and mask if present)
            are read. Not replaced -- relationships are appended to
            `scene.relationships`.

        Returns
        -------
        The same `Scene`, with one `Relationship` appended per pair of
        detections.
        """

        detections = scene.detections

        for index_a, index_b in combinations(range(len(detections)), 2):

            relationship = self._infer_relationship(
                index_a,
                detections[index_a],
                index_b,
                detections[index_b],
            )

            scene.relationships.append(relationship)

            near_relationship = self._infer_near_relationship(
                index_a, detections[index_a], index_b, detections[index_b]
            )

            if near_relationship is not None:
                scene.relationships.append(near_relationship)

        return scene

    ##################################################
    # Helpers
    ##################################################

    def _infer_relationship(self, index_a, detection_a, index_b, detection_b):
        """
        Decides the single relationship that best describes how
        `detection_a` and `detection_b` relate, and returns it as a
        `Relationship` referencing `index_a`/`index_b`.
        """

        area_a = self._detection_area(detection_a)
        area_b = self._detection_area(detection_b)

        intersection = self._intersection_area(detection_a, detection_b)

        if intersection <= 0:
            return self._directional_relationship(
                index_a, detection_a, index_b, detection_b
            )

        contained_a = intersection / area_a if area_a > 0 else 0.0
        contained_b = intersection / area_b if area_b > 0 else 0.0

        if contained_a >= INSIDE_THRESHOLD:
            return Relationship(
                subject_id=index_a,
                predicate=RelationshipType.INSIDE,
                object_id=index_b,
                confidence=min(1.0, contained_a),
                metadata={"intersection_area": intersection},
            )

        if contained_b >= INSIDE_THRESHOLD:
            return Relationship(
                subject_id=index_b,
                predicate=RelationshipType.INSIDE,
                object_id=index_a,
                confidence=min(1.0, contained_b),
                metadata={"intersection_area": intersection},
            )

        union = area_a + area_b - intersection
        iou = intersection / union if union > 0 else 0.0

        predicate = (
            RelationshipType.OVERLAPS
            if iou >= OVERLAP_IOU_THRESHOLD
            else RelationshipType.INTERSECTS
        )

        return Relationship(
            subject_id=index_a,
            predicate=predicate,
            object_id=index_b,
            confidence=min(1.0, iou) if predicate == RelationshipType.OVERLAPS else 1.0,
            metadata={"intersection_area": intersection, "iou": iou},
        )

    def _infer_near_relationship(self, index_a, detection_a, index_b, detection_b):
        """Returns a `NEAR` `Relationship` if both detections have a
        `position_3d` within `NEAR_DISTANCE_THRESHOLD_M` of each other,
        else `None`. See module docstring -- this is additive to, never
        a replacement for, the 2D relationship for the same pair."""

        position_a = detection_a.position_3d
        position_b = detection_b.position_3d

        if position_a is None or position_b is None:
            return None

        distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(position_a, position_b)))

        if distance > NEAR_DISTANCE_THRESHOLD_M:
            return None

        return Relationship(
            subject_id=index_a,
            predicate=RelationshipType.NEAR,
            object_id=index_b,
            confidence=1.0 - (distance / NEAR_DISTANCE_THRESHOLD_M),
            metadata={"distance_3d_m": distance},
        )

    def _directional_relationship(self, index_a, detection_a, index_b, detection_b):
        """
        Builds a `LEFT_OF`/`RIGHT_OF`/`ABOVE`/`BELOW` relationship from
        two non-overlapping detections' bounding-box centers.

        The axis with the larger center-to-center displacement decides
        whether the pair is described horizontally or vertically;
        image coordinates grow downward, so a larger `y` means lower
        in the frame (`BELOW`).
        """

        center_a = self._bbox_center(detection_a.bbox)
        center_b = self._bbox_center(detection_b.bbox)

        dx = center_b[0] - center_a[0]
        dy = center_b[1] - center_a[1]

        dominant = max(abs(dx), abs(dy))
        confidence = dominant / (abs(dx) + abs(dy)) if (dx or dy) else 0.5

        if abs(dx) >= abs(dy):
            predicate = (
                RelationshipType.LEFT_OF if dx > 0 else RelationshipType.RIGHT_OF
            )
        else:
            predicate = RelationshipType.ABOVE if dy > 0 else RelationshipType.BELOW

        return Relationship(
            subject_id=index_a,
            predicate=predicate,
            object_id=index_b,
            confidence=confidence,
            metadata={"dx": dx, "dy": dy},
        )

    def _detection_area(self, detection):
        """
        Returns the best available area for a detection: its mask's
        pixel count if segmented, otherwise its bounding-box area.
        """

        if detection.mask is not None:
            return detection.mask.area

        return self._bbox_area(detection.bbox)

    def _intersection_area(self, detection_a, detection_b):
        """
        Returns the overlap area between two detections: exact pixel
        overlap if both are segmented, otherwise bounding-box overlap.
        """

        if detection_a.mask is not None and detection_b.mask is not None:
            return int((detection_a.mask.binary & detection_b.mask.binary).sum())

        return self._bbox_intersection_area(detection_a.bbox, detection_b.bbox)

    def _bbox_area(self, bbox):
        """Returns a `[x1, y1, x2, y2]` bounding box's pixel area."""

        x1, y1, x2, y2 = bbox

        return max(0.0, x2 - x1) * max(0.0, y2 - y1)

    def _bbox_center(self, bbox):
        """Returns a `[x1, y1, x2, y2]` bounding box's `(x, y)` center."""

        x1, y1, x2, y2 = bbox

        return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)

    def _bbox_intersection_area(self, bbox_a, bbox_b):
        """Returns the overlap area between two `[x1, y1, x2, y2]` boxes."""

        ax1, ay1, ax2, ay2 = bbox_a
        bx1, by1, bx2, by2 = bbox_b

        overlap_x = max(0.0, min(ax2, bx2) - max(ax1, bx1))
        overlap_y = max(0.0, min(ay2, by2) - max(ay1, by1))

        return overlap_x * overlap_y

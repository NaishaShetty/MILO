"""
scene_visualizer.py

Purpose
-------
Renders a `Scene` (bounding boxes, labels, confidences, segmentation
masks) onto its source RGB image using OpenCV only.

Responsibilities
-----------------
- Implement `BaseVisualizer`: turn `(image, scene)` into a new
  annotated image, without ever mutating either argument.
- Own exactly the drawing logic -- rectangles, filled label
  backgrounds, text, and alpha-blended masks -- split into small,
  single-purpose helper methods (`_draw_mask`, `_draw_box`,
  `_draw_label`) rather than one large function.
- Derive a deterministic color per object label, so the same label
  (e.g. "refrigerator") always renders in the same color across runs
  and across frames.

Why this abstraction exists
-----------------------------
`SceneVisualizer` only understands `Scene` -- it has no knowledge of
Grounding DINO, SAM2, or any other model that produced the detections
and masks it draws. This is deliberate: rendering is a presentation
concern, perception is an inference concern, and coupling them would
mean every future perception stage (depth, tracking, scene-graph
relationships) needs its own bespoke drawing code. Because this class
depends only on the `Scene`/`Detection`/`Mask` data model, any future
producer of a `Scene` can reuse this exact renderer unchanged.

Rendering order
------------------
1. Start from the raw RGB image.
2. Draw all masks (semi-transparent, alpha-blended).
3. Draw all bounding boxes on top of the masks.
4. Draw all labels/confidences on top of the boxes.

Masks are drawn before boxes/labels so that box outlines and text
remain crisp and readable instead of being dimmed by mask blending
drawn afterward.

Phase 3.x: tracking ID and depth
-------------------------------------
When a detection carries `tracking_id` and/or `depth` (i.e. a tracker
and/or depth stage ran before this renders), the label text grows to
include them: `"mug 0.94 #3 1.84m"`. Both are optional and independently
guarded (`if detection.tracking_id is not None` / `if detection.depth is
not None`) so a Phase-2-only `Scene` (no tracker/depth configured)
renders exactly as before -- this stays a strict superset of the
existing behavior, never a breaking change to it. Per the project's
"avoid displaying every internal field" requirement, this deliberately
does NOT draw `position_3d`, `track_status`, or any `attributes` value
on the image itself -- those belong in the object inspector (a
structured UI element with room for them), not crammed into overlay
text where they'd make every label unreadable.

Color determinism
--------------------
Colors are derived from `hashlib.md5(label)` rather than
`random`/`hash()`. Python's built-in `hash()` is salted per-process
(`PYTHONHASHSEED`), so the same label would get a different color on
every run unless that salt is fixed. `md5` is stable across processes
and interpreters, which is what "identical label -> identical color
every run" actually requires.
"""

import hashlib

import cv2

from vision.visualization.base_visualizer import BaseVisualizer

MASK_ALPHA = 0.35

BOX_THICKNESS = 2

FONT = cv2.FONT_HERSHEY_SIMPLEX

FONT_SCALE = 0.55

FONT_THICKNESS = 1

LABEL_TEXT_COLOR = (255, 255, 255)


class SceneVisualizer(BaseVisualizer):
    """
    Draws a `Scene`'s detections and masks onto its source image using
    OpenCV, leaving both the image and the `Scene` untouched.
    """

    def process(self, image, scene):
        """
        See `BaseVisualizer.process`. Delegates to `render`, which is
        the name used by callers/tests for this same operation.
        """

        return self.render(image, scene)

    def render(self, image, scene):
        """
        Render `scene` on top of `image` and return a new annotated
        image.

        Parameters
        ----------
        image:
            RGB numpy array -- the frame `scene` was produced from.
            Not modified; a copy is drawn on instead.

        scene:
            The `Scene` to render. Not modified.

        Returns
        -------
        A new RGB numpy array with masks, boxes, and labels drawn on
        top of `image`.
        """

        annotated = image.copy()

        for detection in scene.detections:

            if detection.mask is not None:

                color = self._color_for_label(detection.label)

                annotated = self._draw_mask(annotated, detection.mask.binary, color)

        for detection in scene.detections:

            color = self._color_for_label(detection.label)

            self._draw_box(annotated, detection.bbox, color)

        for detection in scene.detections:

            color = self._color_for_label(detection.label)

            self._draw_label(annotated, detection, color)

        return annotated

    ##################################################
    # Helpers
    ##################################################

    def _color_for_label(self, label):
        """
        Derives a deterministic BGR color from an object label.

        The same label always hashes to the same color, in this run
        and in every future run, because it is derived from `md5`
        rather than Python's per-process-salted `hash()`.
        """

        digest = hashlib.md5(label.encode("utf-8")).digest()

        # Fixed offset/scale keeps colors away from near-black, which
        # would be invisible against a dark scene and hard to read
        # text on top of.
        b = 60 + digest[0] % 180
        g = 60 + digest[1] % 180
        r = 60 + digest[2] % 180

        return (int(b), int(g), int(r))

    def _draw_mask(self, image, binary_mask, color):
        """
        Alpha-blends a single boolean mask onto `image` in `color`.

        Returns a new image; `image` itself is not modified.
        """

        overlay = image.copy()

        overlay[binary_mask.astype(bool)] = color

        return cv2.addWeighted(overlay, MASK_ALPHA, image, 1 - MASK_ALPHA, 0)

    def _draw_box(self, image, bbox, color):
        """
        Draws a single bounding-box rectangle on `image` in place.
        """

        x1, y1, x2, y2 = map(int, bbox)

        cv2.rectangle(image, (x1, y1), (x2, y2), color, BOX_THICKNESS)

    def _draw_label(self, image, detection, color):
        """
        Draws a filled label background plus "<label> <confidence>
        [#<tracking_id>] [<depth>m]" text above a bounding box, on
        `image` in place. The tracking-id/depth suffixes only appear
        when that detection has them set -- see module docstring.
        """

        x1, y1, _, _ = map(int, detection.bbox)

        text = f"{detection.label} {detection.confidence:.2f}"

        if detection.tracking_id is not None:
            text += f" #{detection.tracking_id}"

        if detection.depth is not None:
            text += f" {detection.depth:.2f}m"

        (text_w, text_h), baseline = cv2.getTextSize(
            text, FONT, FONT_SCALE, FONT_THICKNESS
        )

        # Keep the label background inside the image when the box's
        # top edge is near the top of the frame.
        bg_y2 = max(y1, text_h + baseline + 4)
        bg_y1 = bg_y2 - text_h - baseline - 4

        cv2.rectangle(
            image,
            (x1, bg_y1),
            (x1 + text_w + 6, bg_y2),
            color,
            -1,
        )

        cv2.putText(
            image,
            text,
            (x1 + 3, bg_y2 - baseline - 2),
            FONT,
            FONT_SCALE,
            LABEL_TEXT_COLOR,
            FONT_THICKNESS,
            cv2.LINE_AA,
        )

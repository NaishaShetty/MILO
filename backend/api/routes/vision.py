"""
vision.py (backend/api/routes)

Purpose
-------
Implements `POST /api/v1/vision/perceive` -- the HTTP entry point for
the Phase 3.x Vision subsystem, mirroring `routes/language.py`'s shape
and boundary discipline (thin HTTP wrapper, no perception logic of its
own). Calls the existing `VisionSystem` (`vision/factory.py`) built once
at startup, translates its `Scene` into the API's `SpatialObject`/
`PerceptionStatus`/`SceneChangeModel` shapes, and renders the annotated
camera/depth images server-side -- the frontend never touches a model,
the simulator, or a `Detection`/`Track` dataclass directly (see
`api/models/vision.py`'s module docstring on the API/frontend boundary).

Why this endpoint is unavailable-safe (503, not a crash)
--------------------------------------------------------------
AI2-THOR requires a Unity binary this process may not have access to
(a CI runner, this repository's own development sandbox, or a headless
deployment without the simulator installed). `api/app.py`'s lifespan
attempts to build a `VisionSystem` and leaves `app.state.vision_system =
None` on failure rather than crashing the whole API (which would also
take down the unrelated, simulator-independent Language API). This
route's dependency function maps that `None` to a clean 503 -- exactly
analogous to `routes/language.py` mapping a `ConfigurationError` to 503,
just detected earlier (at dependency-resolution time, not inside a
`try`), since "no simulator" is a startup-time fact, not a per-request
failure mode.

Scope note (frame acquisition happening twice per request)
------------------------------------------------------------------
`VisionAgent.perceive()` already fetches the current RGB frame
internally; this route also calls `agent.get_rgb_image()` once more to
have the raw frame available for rendering. Both reads happen without
any `simulator.move_*()`/`turn_*()` call in between, so both return the
same AI2-THOR frame (`controller.last_event.frame` is only replaced by
an action step -- see `simulator/ai2thor_env.py`) -- this is the same
same-frame assumption `GroundTruthDepthEstimator`'s docstring already
documents for depth/RGB consistency, extended here to cover the
render-image fetch too.
"""

from __future__ import annotations

import base64
import logging
from typing import List, Optional

import cv2
from fastapi import APIRouter, Depends, HTTPException, Request

from api.models.vision import (
    DepthLegend,
    PerceiveRequest,
    PerceiveResponse,
    PerceptionStatus,
    SceneChangeModel,
    SpatialObject,
)
from scene.metadata_keys import SceneMetadata
from vision.factory import VisionSystem
from vision.visualization.depth_visualizer import DepthVisualizer
from vision.visualization.scene_visualizer import SceneVisualizer

logger = logging.getLogger(__name__)

router = APIRouter()

_scene_visualizer = SceneVisualizer()
_depth_visualizer = DepthVisualizer()

_VISION_UNAVAILABLE_MESSAGE = (
    "The vision system is not available on this server (no simulator "
    "connection). See backend/docs/spatial_perception.md."
)


def get_vision_system(request: Request) -> VisionSystem:
    """FastAPI dependency returning the `VisionSystem` constructed at
    application startup (`api/app.py`'s `_lifespan`). Raises 503 if
    startup could not construct one -- see module docstring. A
    dependency function (rather than a module-level global) keeps this
    route testable via `app.dependency_overrides`, exactly like
    `routes/language.py::get_language_agent`."""

    vision_system = request.app.state.vision_system

    if vision_system is None:
        raise HTTPException(
            status_code=503,
            detail={
                "category": "vision_unavailable",
                "message": _VISION_UNAVAILABLE_MESSAGE,
            },
        )

    return vision_system


def _encode_png_base64(image_rgb) -> str:
    """Encodes an RGB `numpy.ndarray` as a base64 PNG string.

    Converts to BGR before `cv2.imencode` -- OpenCV's encoders write
    whatever channel order they're given as if it were BGR (matching
    `vision/visualization/test_visualizer.py`'s existing
    `cv2.cvtColor(..., cv2.COLOR_RGB2BGR)` step before `cv2.imwrite`);
    skipping this would swap red and blue in the resulting PNG.
    """

    bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)
    success, buffer = cv2.imencode(".png", bgr)

    if not success:
        raise RuntimeError("Failed to encode image as PNG.")

    return base64.b64encode(buffer.tobytes()).decode("ascii")


def _to_spatial_object(
    detection, tracker, depth_source: Optional[str]
) -> SpatialObject:
    """Projects one `Detection` (+ its matching `Track`, if tracked)
    into the API's `SpatialObject` shape. See
    `api/models/vision.py`'s module docstring for why this projection
    is hand-written rather than automatic."""

    track = None
    if tracker is not None and detection.tracking_id is not None:
        track = tracker.tracks.get(detection.tracking_id)

    return SpatialObject(
        object_id=detection.tracking_id,
        label=detection.label,
        confidence=detection.confidence,
        bbox=list(detection.bbox),
        depth=detection.depth,
        depth_source=depth_source if detection.depth is not None else None,
        position_3d=detection.position_3d,
        track_status=detection.attributes.get("track_status"),
        frames_observed=track.frame_count if track is not None else None,
        first_seen=track.first_seen if track is not None else None,
        last_seen=track.last_seen if track is not None else None,
    )


def _to_status(
    objects: List[SpatialObject], depth_source: Optional[str]
) -> PerceptionStatus:
    return PerceptionStatus(
        object_count=len(objects),
        tracked_count=sum(1 for o in objects if o.track_status is not None),
        depth_available_count=sum(1 for o in objects if o.depth is not None),
        depth_source=depth_source,
    )


@router.post(
    "/perceive",
    response_model=PerceiveResponse,
    summary="Perceive the current scene",
    description=(
        "Runs the full Phase 3.x perception pipeline (detection, "
        "segmentation, depth, tracking, scene graph) on the simulator's "
        "current frame and returns the resulting spatial objects, "
        "temporal changes since the previous call, and server-rendered "
        "annotated images. Does NOT plan, execute robot actions, or "
        "combine this with any Language Understanding result -- see "
        "docs/architecture/spatial_perception.md."
    ),
    responses={
        503: {"description": "The vision system is not available on this server."},
        500: {"description": "An unexpected internal error occurred."},
    },
)
def perceive(
    body: PerceiveRequest,
    vision_system: VisionSystem = Depends(get_vision_system),
) -> PerceiveResponse:
    scene = vision_system.agent.perceive(body.prompt)
    image = vision_system.agent.get_rgb_image()

    changes = vision_system.temporal_scene.update(scene, tracker=vision_system.tracker)

    depth_source = scene.metadata.get(SceneMetadata.DEPTH_SOURCE)

    objects = [
        _to_spatial_object(detection, vision_system.tracker, depth_source)
        for detection in scene.detections
    ]

    camera_image = _scene_visualizer.render(image, scene)
    camera_image_png_b64 = _encode_png_base64(camera_image)

    depth_image, legend = _depth_visualizer.render(image, scene)
    depth_image_png_b64 = (
        _encode_png_base64(depth_image) if depth_image is not None else None
    )
    depth_legend = (
        DepthLegend(
            min_depth_m=legend.min_depth_m,
            max_depth_m=legend.max_depth_m,
            colormap_name=legend.colormap_name,
            near_is=legend.near_is,
        )
        if legend is not None
        else None
    )

    return PerceiveResponse(
        objects=objects,
        status=_to_status(objects, depth_source),
        scene_changes=[
            SceneChangeModel(
                change_type=change.change_type.value,
                tracking_id=change.tracking_id,
                label=change.label,
                detail=change.detail,
            )
            for change in changes
        ],
        camera_image_png_b64=camera_image_png_b64,
        depth_image_png_b64=depth_image_png_b64,
        depth_legend=depth_legend,
    )

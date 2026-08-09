"""
vision.py (backend/api/models)

Purpose
-------
Defines the request/response envelope for `POST /api/v1/vision/perceive`
-- the one endpoint Phase 3.x adds to expose the Vision subsystem over
HTTP. Mirrors `api/models/language.py`'s pattern (see that module's
docstring): validate the request, and for the response, reuse real
domain data wherever it already exists rather than re-deriving it.

Why this file CANNOT just import `Detection`/`Track` like `language.py`
imports `ParsedInstruction`
-----------------------------------------------------------------------------
`api/models/language.py` embeds the *actual* `schemas.task.ParsedInstruction`
Pydantic model directly, because that model already is Pydantic --
FastAPI serializes it as-is, with no risk of drifting from what
`LanguageAgent` actually produced. `scene.detection.Detection` and
`vision.tracking.track.Track`, by contrast, are plain `dataclasses` (see
`scene/detection.py`'s module docstring on why -- a design predating
this API and frozen by the Phase 2 API freeze, not something this file
can change). A Pydantic response model cannot embed a dataclass directly
and get schema/validation for free the way it can a `BaseModel`, so
`SpatialObject` below is necessarily a hand-declared field-for-field
projection, built by `api/routes/vision.py` from a `Detection` (+ the
matching `Track`, when tracking is enabled). Keep this projection in
sync with `Detection`'s field set by hand if that dataclass ever grows a
new field worth exposing -- there is no automatic mechanism to catch
drift here, unlike the language API's `ParsedInstruction` reuse.

Security note
-------------
Nothing in this module can carry a credential -- perception has none to
leak (unlike the language API's LLM provider key). `camera_image_png_b64`/
`depth_image_png_b64` are rendered server-side (see
`vision/visualization/`) specifically so the frontend never runs a model
or touches raw simulator/model output itself -- see the project's
API/frontend boundary requirement.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class PerceiveRequest(BaseModel):
    """Request body for `POST /api/v1/vision/perceive`."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(
        min_length=1,
        max_length=500,
        description="Grounding DINO detection prompt, e.g. "
        "'chair. table. mug. apple. bottle. refrigerator.'.",
        examples=["chair. table. mug. apple. bottle. refrigerator."],
    )


class SpatialObject(BaseModel):
    """One perceived object, combining a `Detection` with its `Track`
    state (when a tracker is configured and has matched it) -- see
    module docstring for why this is a hand-projected model rather than
    a direct dataclass embed.

    Field-for-field provenance:
        object_id, label, confidence, bbox, depth, position_3d,
        track_status: `Detection` (`scene/detection.py`).
        depth_source: `Scene.metadata[SceneMetadata.DEPTH_SOURCE]` --
            shared across every detection in one response (see
            `base_depth_estimator.py`), repeated per-object here purely
            for the frontend's convenience (no per-object join needed).
        frames_observed, first_seen, last_seen: the matching
            `vision.tracking.track.Track`, looked up by `object_id` --
            `None` when no tracker is configured.
    """

    object_id: Optional[int] = Field(
        default=None,
        description="Persistent tracking ID (Detection.tracking_id). "
        "None if no tracker is configured.",
    )
    label: str = Field(description="Object class name, e.g. 'mug'.")
    confidence: float = Field(description="Detector confidence, in [0, 1].")
    bbox: List[float] = Field(description="[x1, y1, x2, y2] pixel bounding box.")
    depth: Optional[float] = Field(
        default=None,
        description="Robust object-level depth (see "
        "base_depth_estimator.py). Units depend on depth_source: meters "
        "for 'ground_truth', a unitless relative pseudo-depth for "
        "'depth_anything' -- never treat the latter as meters.",
    )
    depth_source: Optional[str] = Field(
        default=None,
        description="'ground_truth' or 'depth_anything' -- which depth "
        "source produced this scene's depth. None if no depth stage ran.",
    )
    position_3d: Optional[List[float]] = Field(
        default=None,
        description="[x, y, z] camera-space position, meters (see "
        "vision/spatial/localization.py for the coordinate convention). "
        "None if depth or camera intrinsics were unavailable.",
    )
    track_status: Optional[str] = Field(
        default=None,
        description="Current TrackStatus value ('new', 'tracked', "
        "'temporarily_lost', 'reacquired', 'lost'). None if untracked.",
    )
    frames_observed: Optional[int] = Field(
        default=None,
        description="Track.frame_count -- frames this object has "
        "been matched to a detection, excluding missed frames.",
    )
    first_seen: Optional[int] = Field(
        default=None, description="Frame index this object's track was created on."
    )
    last_seen: Optional[int] = Field(
        default=None, description="Frame index this object was last matched on."
    )


class SceneChangeModel(BaseModel):
    """Mirrors `vision.temporal.scene_diff.SceneChange` -- see that
    dataclass's docstring for field meanings."""

    change_type: str = Field(
        description="'new', 'removed', 'moved', 'occluded', or 'reappeared'."
    )
    tracking_id: int
    label: str
    detail: str


class DepthLegend(BaseModel):
    """Mirrors `vision.visualization.depth_visualizer.DepthColormapLegend`
    -- required alongside `depth_image_png_b64` so a client never shows
    depth colors without the scale they mean (see that module's
    docstring)."""

    min_depth_m: float
    max_depth_m: float
    colormap_name: str
    near_is: str


class PerceptionStatus(BaseModel):
    """Scene-level summary counts -- the "Perception" panel's numbers in
    the project's recommended UI layout."""

    object_count: int = Field(description="Total detections this frame.")
    tracked_count: int = Field(
        description="Detections with a non-None track_status this frame."
    )
    depth_available_count: int = Field(
        description="Detections with a non-None depth this frame."
    )
    depth_source: Optional[str] = Field(
        default=None, description="'ground_truth', 'depth_anything', or None."
    )


class PerceiveResponse(BaseModel):
    """Successful response body for `POST /api/v1/vision/perceive`."""

    objects: List[SpatialObject]
    status: PerceptionStatus
    scene_changes: List[SceneChangeModel] = Field(
        default_factory=list,
        description="Changes since the previous call to this endpoint "
        "for this process (see TemporalScene) -- empty on the first call.",
    )
    camera_image_png_b64: str = Field(
        description="Base64-encoded PNG: the RGB frame with detections/"
        "masks/tracking IDs/depth annotated, rendered server-side."
    )
    depth_image_png_b64: Optional[str] = Field(
        default=None,
        description="Base64-encoded PNG depth colormap. None if no "
        "depth was available this frame.",
    )
    depth_legend: Optional[DepthLegend] = Field(
        default=None,
        description="Required companion to depth_image_png_b64 -- see "
        "DepthLegend's docstring. Always present together with the image.",
    )


class ErrorResponse(BaseModel):
    """Documented shape of every non-2xx response this API returns --
    same shape as `api/models/language.py`'s `ErrorResponse`, redeclared
    here (not imported) to keep the vision and language API modules
    independent, per that module's own domain-separation rationale."""

    category: str = Field(
        description="Machine-readable failure category, e.g. "
        "'invalid_request', 'vision_unavailable', 'internal_error'.",
    )
    message: str = Field(
        description="Human-readable, credential-free description of " "what went wrong."
    )

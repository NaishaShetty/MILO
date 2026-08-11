// visionTypes.ts
//
// Purpose
// -------
// TypeScript types for the Phase 3.x Vision API
// (`POST /api/v1/vision/perceive`) served by `backend/api/routes/vision.py`.
// A separate file from `types.ts` (the Language API's own types) rather
// than one shared file -- mirrors `vision.ts` being a separate file from
// `language.ts` (see that file's docstring): the two APIs are
// independent domains that happen to share a backend process, and
// keeping their types apart means neither file needs to change when the
// other's contract does.
//
// Like `types.ts`, this is a *view* of `backend/api/models/vision.py`'s
// Pydantic models -- only the fields this UI renders, not a mechanical
// field-for-field port.

export interface SpatialObject {
  object_id: number | null;
  label: string;
  confidence: number;
  bbox: [number, number, number, number];
  depth: number | null;
  depth_source: DepthSource | null;
  position_3d: [number, number, number] | null;
  track_status: TrackStatus | null;
  frames_observed: number | null;
  first_seen: number | null;
  last_seen: number | null;
}

// Deliberate "loose autocomplete" idiom, see api/types.ts::ErrorCategory.
// eslint-disable-next-line @typescript-eslint/ban-types
export type DepthSource = "ground_truth" | "depth_anything" | (string & {});

export type TrackStatus =
  | "new"
  | "tracked"
  | "temporarily_lost"
  | "reacquired"
  | "lost"
  // eslint-disable-next-line @typescript-eslint/ban-types -- see DepthSource above.
  | (string & {});

export type SceneChangeType =
  | "new"
  | "removed"
  | "moved"
  | "occluded"
  | "reappeared"
  // eslint-disable-next-line @typescript-eslint/ban-types -- see DepthSource above.
  | (string & {});

export interface SceneChange {
  change_type: SceneChangeType;
  tracking_id: number;
  label: string;
  detail: string;
}

export interface DepthLegend {
  min_depth_m: number;
  max_depth_m: number;
  colormap_name: string;
  near_is: string;
}

export interface PerceptionStatus {
  object_count: number;
  tracked_count: number;
  depth_available_count: number;
  depth_source: DepthSource | null;
}

// Mirrors `backend/api/models/vision.py`'s `PerceiveResponse`.
export interface PerceiveResponse {
  objects: SpatialObject[];
  status: PerceptionStatus;
  scene_changes: SceneChange[];
  camera_image_png_b64: string;
  depth_image_png_b64: string | null;
  depth_legend: DepthLegend | null;
}

// Mirrors `backend/api/models/vision.py`'s `ErrorResponse`.
export type VisionErrorCategory =
  | "invalid_request"
  | "vision_unavailable"
  | "internal_error"
  // eslint-disable-next-line @typescript-eslint/ban-types -- see DepthSource above.
  | (string & {});

export interface VisionApiErrorBody {
  category: VisionErrorCategory;
  message: string;
}

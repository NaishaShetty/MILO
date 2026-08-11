// CameraPanel.tsx
//
// Purpose
// -------
// Displays the robot's camera feed with detections/masks/tracking
// IDs/depth already annotated -- rendered entirely server-side
// (`backend/vision/visualization/scene_visualizer.py`) and delivered as
// a base64 PNG in `PerceiveResponse.camera_image_png_b64`. This
// component only decides *whether* to show an image (idle/loading/
// error/empty states) -- it never draws a box, computes a color, or
// touches a `Detection`; per the project's API/frontend boundary, all
// of that stays in the backend so this file has zero perception logic
// of its own.
//
// Mission Control visual pass: adds chrome around the same image --
// a "LIVE" badge (shown only once a real frame exists, never a
// standing claim), a fullscreen toggle (pure CSS/local state, no new
// data), and the real robot position rendered via `RobotMiniMap` in
// the bottom-left corner, matching the reference dashboard's camera
// panel without touching how the image itself is fetched or rendered.
import { useState } from "react";
import { RobotMiniMap } from "./RobotMiniMap";

interface CameraPanelProps {
  imageBase64: string | null;
  isLoading: boolean;
  robotPosition?: { x: number; z: number } | null;
}

function ExpandIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" aria-hidden="true">
      <path
        d="M6 2H2v4M10 2h4v4M6 14H2v-4M10 14h4v-4"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function CameraPanel({ imageBase64, isLoading, robotPosition = null }: CameraPanelProps) {
  const [fullscreen, setFullscreen] = useState(false);

  return (
    <div className={"camera-panel" + (fullscreen ? " camera-panel--fullscreen" : "")}>
      <h2 className="camera-panel__title sr-only">Camera</h2>
      <div className="camera-panel__frame">
        {isLoading && <p className="camera-panel__placeholder">Perceiving current scene...</p>}
        {!isLoading && !imageBase64 && (
          <p className="camera-panel__placeholder">
            No camera frame yet. Perceive the scene to see it here.
          </p>
        )}
        {!isLoading && imageBase64 && (
          <img
            className="camera-panel__image"
            src={`data:image/png;base64,${imageBase64}`}
            alt="Annotated camera view with detections, segmentation, tracking IDs, and depth"
          />
        )}

        {!isLoading && imageBase64 && (
          <span className="camera-panel__live-badge">
            <span className="camera-panel__live-dot" aria-hidden="true" />
            LIVE
          </span>
        )}

        <button
          type="button"
          className="camera-panel__expand"
          onClick={() => setFullscreen((value) => !value)}
          aria-pressed={fullscreen}
          aria-label={fullscreen ? "Exit fullscreen" : "View fullscreen"}
          title={fullscreen ? "Exit fullscreen" : "View fullscreen"}
        >
          <ExpandIcon />
        </button>

        {!isLoading && imageBase64 && (
          <RobotMiniMap position={robotPosition} size="sm" className="camera-panel__minimap" />
        )}
      </div>
    </div>
  );
}

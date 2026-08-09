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
interface CameraPanelProps {
  imageBase64: string | null;
  isLoading: boolean;
}

export function CameraPanel({ imageBase64, isLoading }: CameraPanelProps) {
  return (
    <div className="camera-panel">
      <h2 className="camera-panel__title">Camera</h2>
      <div className="camera-panel__frame">
        {isLoading && (
          <p className="camera-panel__placeholder">Perceiving current scene...</p>
        )}
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
      </div>
    </div>
  );
}

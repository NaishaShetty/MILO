// ObjectInspectorTable.tsx
//
// Purpose
// -------
// The "OBJECT INSPECTOR" from the project's recommended dashboard
// layout: one row per perceived `SpatialObject`, showing id/label/
// depth/position/track status at a glance. This is the structured
// place for fields the camera overlay deliberately keeps off the image
// itself (full 3D position, frames observed, first/last seen) -- see
// `CameraPanel`'s docstring and the project's "avoid displaying every
// internal field on the image" requirement.
import type { SpatialObject } from "../api/visionTypes";

interface ObjectInspectorTableProps {
  objects: SpatialObject[];
}

function formatPosition(position: SpatialObject["position_3d"]): string {
  if (!position) {
    return "—";
  }
  const [x, y, z] = position;
  return `(${x.toFixed(2)}, ${y.toFixed(2)}, ${z.toFixed(2)})`;
}

function formatDepth(object: SpatialObject): string {
  if (object.depth === null) {
    return "—";
  }
  const unit = object.depth_source === "ground_truth" ? "m" : "";
  return `${object.depth.toFixed(2)}${unit}`;
}

export function ObjectInspectorTable({ objects }: ObjectInspectorTableProps) {
  if (objects.length === 0) {
    return (
      <div className="object-inspector">
        <h2 className="object-inspector__title">Object Inspector</h2>
        <p className="object-inspector__empty">No objects perceived yet.</p>
      </div>
    );
  }

  return (
    <div className="object-inspector">
      <h2 className="object-inspector__title">Object Inspector</h2>
      <div className="object-inspector__scroll">
        <table className="object-inspector__table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Object</th>
              <th>Confidence</th>
              <th>Depth</th>
              <th>Position (x, y, z)</th>
              <th>Status</th>
              <th>Frames</th>
            </tr>
          </thead>
          <tbody>
            {objects.map((object, index) => (
              <tr key={object.object_id ?? `unknown-${index}`}>
                <td>{object.object_id !== null ? `#${object.object_id}` : "—"}</td>
                <td>{object.label}</td>
                <td>{(object.confidence * 100).toFixed(0)}%</td>
                <td>{formatDepth(object)}</td>
                <td>{formatPosition(object.position_3d)}</td>
                <td>
                  {object.track_status ? (
                    <span
                      className={`object-inspector__status object-inspector__status--${object.track_status}`}
                    >
                      {object.track_status.replace("_", " ").toUpperCase()}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td>{object.frames_observed ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

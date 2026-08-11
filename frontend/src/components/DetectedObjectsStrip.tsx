// DetectedObjectsStrip.tsx
//
// Purpose
// -------
// Mission Control's "Detected Objects" panel: a horizontal card strip
// view of the same real `SpatialObject[]` `VisionPanel` already
// fetches via `perceive()` (mirrored out through its `onObjectsChange`
// callback -- see that component's docstring), styled per the
// reference dashboard instead of `ObjectInspectorTable`'s dense table.
// Never fabricates a card: `objects` is `null` until a real perceive
// response exists, and empty renders the literal "No objects detected
// yet." (spec section 19) -- no mock confidences, no invented
// locations.
import type { SpatialObject } from "../api/visionTypes";

function ObjectIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
      <rect x="4" y="4" width="16" height="16" rx="3" stroke="currentColor" strokeWidth="1.4" />
      <path d="M4 9h16M9 4v16" stroke="currentColor" strokeWidth="1.2" opacity="0.6" />
    </svg>
  );
}

interface DetectedObjectsStripProps {
  objects: SpatialObject[] | null;
}

export function DetectedObjectsStrip({ objects }: DetectedObjectsStripProps) {
  if (!objects || objects.length === 0) {
    return <p className="detected-objects__empty">No objects detected yet.</p>;
  }

  return (
    <ul className="detected-objects" aria-label="Detected objects">
      {objects.map((object, index) => (
        <li key={object.object_id ?? `unknown-${index}`} className="detected-objects__card">
          <span className="detected-objects__thumb" aria-hidden="true">
            <ObjectIcon />
          </span>
          <span className="detected-objects__name">{object.label}</span>
          <span className="detected-objects__confidence">{(object.confidence * 100).toFixed(0)}%</span>
          {object.track_status && (
            <span
              className={`detected-objects__status detected-objects__status--${object.track_status}`}
            >
              {object.track_status.replace("_", " ")}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

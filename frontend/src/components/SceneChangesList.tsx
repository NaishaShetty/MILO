// SceneChangesList.tsx
//
// Purpose
// -------
// Visibly demonstrates temporal tracking: renders the `SceneChange`s
// (new/removed/moved/occluded/reappeared) since the previous
// `perceive()` call for this session -- the project's requirement that
// the UI "visibly demonstrate temporal tracking," not just show a
// snapshot of the current frame. Empty on the very first perceive call
// (nothing to compare against yet -- see
// `vision/temporal/scene_diff.py`), rendered as a quiet empty state
// rather than an error.
import type { SceneChange } from "../api/visionTypes";

interface SceneChangesListProps {
  changes: SceneChange[];
}

const _ICONS: Record<string, string> = {
  new: "＋",
  removed: "－",
  moved: "→",
  occluded: "◌",
  reappeared: "↺",
};

export function SceneChangesList({ changes }: SceneChangesListProps) {
  return (
    <div className="scene-changes">
      <h2 className="scene-changes__title">Scene Changes</h2>
      {changes.length === 0 ? (
        <p className="scene-changes__empty">No changes since the last perceive call.</p>
      ) : (
        <ul className="scene-changes__list">
          {changes.map((change, index) => (
            <li key={index} className={`scene-changes__item scene-changes__item--${change.change_type}`}>
              <span className="scene-changes__icon">{_ICONS[change.change_type] ?? "•"}</span>
              <span className="scene-changes__label">
                {change.label} #{change.tracking_id}
              </span>
              <span className="scene-changes__detail">{change.detail}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

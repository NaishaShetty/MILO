// RobotMiniMap.tsx
//
// Purpose
// -------
// A small honest position readout, not a floorplan: AI2-THOR doesn't
// give the frontend room geometry, so drawing walls/room labels here
// would be inventing data the backend never sent (see Mission
// Control's "never invent coordinates or distances" rule). Instead
// this renders a bordered map-styled surface with a dot placed from
// the *real* `RobotState.position` (x/z, clamped into view), or an
// honest "Map unavailable" state when there's no live position --
// used both as the camera's small corner overlay and the larger
// "Where Is MILO?" panel.
export interface RobotMiniMapProps {
  position: { x: number; z: number } | null;
  size?: "sm" | "lg";
  className?: string;
}

/** AI2-THOR scenes are typically within roughly +/-6m of the origin on
 * each axis; this only maps a real coordinate into the visible square
 * (clamped, not invented) so the dot stays on the map. */
const RANGE_METERS = 6;

function toPercent(value: number): number {
  const clamped = Math.max(-RANGE_METERS, Math.min(RANGE_METERS, value));
  return ((clamped + RANGE_METERS) / (RANGE_METERS * 2)) * 100;
}

export function RobotMiniMap({ position, size = "sm", className }: RobotMiniMapProps) {
  const classes = ["robot-minimap", `robot-minimap--${size}`, className].filter(Boolean).join(" ");

  return (
    <div className={classes} role="img" aria-label={position ? "MILO's approximate position" : "Map unavailable"}>
      <div className="robot-minimap__grid" aria-hidden="true" />
      {position ? (
        <span
          className="robot-minimap__dot"
          style={{ left: `${toPercent(position.x)}%`, top: `${toPercent(position.z)}%` }}
          title={`x ${position.x.toFixed(2)}, z ${position.z.toFixed(2)}`}
        />
      ) : (
        <span className="robot-minimap__empty">Map unavailable</span>
      )}
    </div>
  );
}

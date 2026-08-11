// RobotStatePanel.tsx
//
// Purpose
// -------
// Mission Control's "Where Is MILO?" robot/simulator panel (Phase 8.6
// spec section 13): renders the live AI2-THOR pose exposed by the new
// `GET /api/v1/tasks/{id}/robot` route (`TaskContext.robotState`,
// polled there -- see that context's docstring). When the simulator
// isn't running (503, `execution_unavailable` -- the same contract
// every other simulator-backed route already uses), this renders an
// explicit "Simulator not connected" status, never a fabricated pose
// -- see spec section 29: offline states must say so, not pretend
// everything is working.
import { ApiError } from "../api/client";
import type { RobotState } from "../api/tasksTypes";
import type { PollingStatus } from "../hooks/usePolling";

function formatVector(vector: { x: number; y: number; z: number } | null): string {
  if (!vector) return "unknown";
  return `x ${vector.x.toFixed(2)}, y ${vector.y.toFixed(2)}, z ${vector.z.toFixed(2)}`;
}

interface RobotStatePanelProps {
  robotState: RobotState | null;
  status: PollingStatus;
  error: unknown;
}

export function RobotStatePanel({ robotState, status, error }: RobotStatePanelProps) {
  const simulatorUnavailable = error instanceof ApiError && error.category === "execution_unavailable";

  if (status === "error" && simulatorUnavailable) {
    return <p className="robot-state-panel__unavailable">Simulator not connected — no live robot state.</p>;
  }

  if (status === "error") {
    return <p className="robot-state-panel__unavailable">Robot state unavailable.</p>;
  }

  if (status === "loading" && !robotState) {
    return <p className="robot-state-panel__unavailable">Loading robot state...</p>;
  }

  if (status === "idle" || !robotState) {
    return <p className="robot-state-panel__unavailable">No robot state yet.</p>;
  }

  return (
    <div className="robot-state-panel">
      <div className="robot-state-panel__grid">
        <div className="robot-state-panel__field">
          <span className="robot-state-panel__field-label">Position</span>
          <span className="robot-state-panel__field-value">{formatVector(robotState.position)}</span>
        </div>
        <div className="robot-state-panel__field">
          <span className="robot-state-panel__field-label">Rotation</span>
          <span className="robot-state-panel__field-value">{formatVector(robotState.rotation)}</span>
        </div>
        <div className="robot-state-panel__field">
          <span className="robot-state-panel__field-label">Camera Tilt</span>
          <span className="robot-state-panel__field-value">
            {robotState.camera_horizon !== null ? `${robotState.camera_horizon.toFixed(1)}°` : "unknown"}
          </span>
        </div>
        <div className="robot-state-panel__field">
          <span className="robot-state-panel__field-label">Holding</span>
          <span className="robot-state-panel__field-value">
            {robotState.held_object
              ? robotState.held_object.object_type ?? robotState.held_object.object_id ?? "object"
              : "nothing"}
          </span>
        </div>
      </div>
      {robotState.visible_objects.length > 0 && (
        <ul className="robot-state-panel__visible" aria-label="Currently visible objects">
          {robotState.visible_objects.map((object, index) => (
            <li key={object.object_id ?? index} className="robot-state-panel__visible-item">
              {object.object_type ?? object.object_id ?? "object"}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

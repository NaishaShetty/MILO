// MissionTrack.tsx -- the progress track: MILO walks along one dot per plan step.
import type { PlanStep } from "../api/plannerTypes";
import type { MiloDirection } from "../state/miloDirector";
import { MiloActor } from "./MiloActor";
import { trackPosition } from "./trackPosition";

export interface MissionTrackProps {
  steps: PlanStep[];
  direction: MiloDirection;
}

export function MissionTrack({ steps, direction }: MissionTrackProps) {
  const position = trackPosition(steps);
  const done = steps.filter((s) => s.status === "completed").length;
  return (
    <div
      className="track"
      role="progressbar"
      aria-label="Mission progress"
      aria-valuemin={0}
      aria-valuemax={steps.length}
      aria-valuenow={done}
    >
      <MiloActor direction={{ ...direction, x: 0.03 + position * 0.94 }} size={56} />
      <div className="track__line">
        <div className="track__fill" style={{ width: `${position * 100}%` }} />
      </div>
      <div className="track__dots">
        {steps.map((step, index) => (
          <span
            key={step.step_id}
            className={
              "track__dot" +
              (step.status === "completed" ? " track__dot--done" : step.status === "running" ? " track__dot--current" : "")
            }
            data-status={step.status}
          >
            {step.status === "completed" ? "✓" : index + 1}
          </span>
        ))}
      </div>
    </div>
  );
}

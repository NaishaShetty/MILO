// trackPosition.ts -- how far along the mission track MILO stands.
import type { PlanStep } from "../api/plannerTypes";

/** 0..1 position of MILO along the track: the number of finished steps over the total. */
export function trackPosition(steps: PlanStep[]): number {
  if (steps.length === 0) return 0;
  return steps.filter((s) => s.status === "completed").length / steps.length;
}

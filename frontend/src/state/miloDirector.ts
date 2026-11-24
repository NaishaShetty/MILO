// miloDirector.ts
//
// Decides what the on-screen MILO is doing -- pose, where he stands, what he
// carries, which way he faces, what he says -- from the REAL task state
// (status, plan, step statuses, explanations), never from a timer.
//   - parsing / planning / reflecting: thinking, at home;
//   - executing: jumps down to the playroom floor and moves along the plan:
//     running while a step is a walk (`navigate`), walking otherwise, and
//     carrying the object between its pickup and its place;
//   - success: back home, arms up; failure: slumped; cancelled: idle.
import type { TaskState } from "../api/tasksTypes";
import type { MiloPose } from "../components/MiloRobot";

export interface MiloDirection {
  pose: MiloPose;
  /** Position along the playroom floor, 0 (home end) .. 1; `null` = at home. */
  x: number | null;
  facing: "left" | "right";
  carrying: string | null;
  speech: string;
}

export const GREETING = "Hi! Give me a job and I will figure it out.";

const THINKING = new Set(["created", "parsing", "retrieving_memory", "planning", "reflecting", "replanning"]);

export function progressOf(task: TaskState | null): { done: number; total: number } {
  const steps = task?.current_plan?.steps ?? [];
  return { done: steps.filter((s) => s.status === "completed").length, total: steps.length };
}

function carriedObject(task: TaskState): string | null {
  let holding: string | null = null;
  for (const step of task.current_plan?.steps ?? []) {
    if (step.status !== "completed") break;
    if (step.action === "pickup") holding = step.target ?? "thing";
    if (step.action === "place" || step.action === "put_down") holding = null;
  }
  return holding;
}

export function directMilo(task: TaskState | null, lastReply?: string | null): MiloDirection {
  const home = { x: null, facing: "right" as const, carrying: null };
  if (!task) {
    return { ...home, pose: lastReply ? "speaking" : "idle", speech: lastReply ?? GREETING };
  }
  const steps = task.current_plan?.steps ?? [];
  const current = steps.find((s) => s.step_id === task.current_step) ?? steps.find((s) => s.status === "running");
  const thought = task.thoughts?.[task.thoughts.length - 1]?.text;
  const speech = current?.explanation ?? thought ?? task.answer ?? GREETING;

  switch (task.status) {
    case "succeeded":
      return { ...home, pose: "success", speech: task.answer ?? thought ?? "All done!" };
    case "failed":
      return { ...home, pose: "error", speech: thought ?? "That didn't work out." };
    case "cancelled":
      return { ...home, pose: "idle", speech: task.cancel_summary ?? "Okay, I stopped." };
    case "executing": {
      const { done, total } = progressOf(task);
      const x = total > 0 ? Math.min(0.92, 0.1 + (done / total) * 0.82) : 0.3;
      return {
        pose: current?.action === "navigate" ? "run" : "walk",
        x,
        facing: "right",
        carrying: carriedObject(task),
        speech,
      };
    }
    default:
      return { ...home, pose: THINKING.has(task.status) ? "thinking" : "idle", speech };
  }
}

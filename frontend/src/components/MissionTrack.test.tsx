import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PlanStep } from "../api/plannerTypes";
import { directMilo } from "../state/miloDirector";
import type { TaskState } from "../api/tasksTypes";
import { MissionTrack } from "./MissionTrack";
import { trackPosition } from "./trackPosition";

const step = (id: number, status: PlanStep["status"]): PlanStep => ({
  step_id: id,
  action: "navigate",
  target: "apple",
  parameters: {},
  description: "",
  preconditions: [],
  postconditions: [],
  status,
});

const eight = (done: number) =>
  Array.from({ length: 8 }, (_, i) => step(i + 1, i < done ? "completed" : i === done ? "running" : "pending"));

describe("MissionTrack", () => {
  it("has one dot per step and reports progress", () => {
    render(<MissionTrack steps={eight(3)} direction={directMilo(null)} />);
    const bar = screen.getByRole("progressbar", { name: "Mission progress" });
    expect(bar).toHaveAttribute("aria-valuenow", "3");
    expect(bar).toHaveAttribute("aria-valuemax", "8");
    expect(bar.querySelectorAll(".track__dot").length).toBe(8);
    expect(bar.querySelectorAll(".track__dot--done").length).toBe(3);
    expect(bar.querySelectorAll(".track__dot--current").length).toBe(1);
  });

  it("moves MILO along as steps finish", () => {
    expect(trackPosition(eight(0))).toBe(0);
    expect(trackPosition(eight(4))).toBe(0.5);
    expect(trackPosition(eight(8))).toBe(1);
    expect(trackPosition([])).toBe(0);
  });
});

describe("miloDirector (pose comes from real task state)", () => {
  const task = (status: string, steps: PlanStep[] = []) =>
    ({ status, current_step: null, thoughts: [], current_plan: { steps }, answer: null }) as unknown as TaskState;

  it("thinks at home while planning", () => {
    expect(directMilo(task("planning"))).toMatchObject({ pose: "thinking", x: null });
  });
  it("runs on the floor while navigating and walks otherwise", () => {
    const running = eight(2);
    const t = { ...task("executing", running), current_step: 3 } as TaskState;
    expect(directMilo(t)).toMatchObject({ pose: "run" });
    expect(directMilo(t).x).not.toBeNull();
  });
  it("carries the object between pickup and place", () => {
    const steps = [
      { ...step(1, "completed"), action: "pickup", target: "apple" },
      { ...step(2, "running"), action: "navigate", target: "fridge" },
    ];
    expect(directMilo({ ...task("executing", steps), current_step: 2 } as TaskState).carrying).toBe("apple");
  });
  it("cheers on success, slumps on failure", () => {
    expect(directMilo(task("succeeded")).pose).toBe("success");
    expect(directMilo(task("failed")).pose).toBe("error");
  });
  it("speaks the current step explanation", () => {
    const steps = [{ ...step(1, "running"), explanation: "Walking to the apple." }];
    expect(directMilo({ ...task("executing", steps), current_step: 1 } as TaskState).speech).toBe("Walking to the apple.");
  });
});

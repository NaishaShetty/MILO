// MissionsPage.test.tsx -- the "working it out" notice for tasks MILO plans itself.
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { MissionsPage } from "./MissionsPage";
import * as taskContext from "../state/useTask";

vi.mock("../state/useTask", () => ({ useTask: vi.fn() }));

function task(planner: string, novel: Record<string, unknown> | null, status = "executing") {
  return {
    task_id: "t1",
    user_request: "chill the apple",
    input_source: "text",
    goal: "novel",
    objects: [],
    target: null,
    current_location: null,
    current_plan: {
      plan_id: "p1",
      task_id: "t1",
      planner_type: planner,
      goal_summary: {},
      steps: [],
      status: "draft",
      created_at: 0,
      metadata: novel ? { novel } : {},
    },
    current_step: null,
    observations: [],
    known_objects: [],
    completed_steps: [],
    execution_history: [],
    failures: [],
    retrieved_memories: [],
    agent_states: {},
    status,
    latencies_ms: {},
    created_memories: [],
    thoughts: [],
    planner,
    planner_note: null,
    cancel_requested: false,
    metrics: { actions: 0, failures: 0, replans: 0, attempts: 0, success: false, total_ms: null },
  };
}

function renderWith(activeTask: unknown, submitInstruction = vi.fn()) {
  vi.mocked(taskContext.useTask).mockReturnValue({
    activeTask,
    activeTaskStatus: "ready",
    history: [],
    setActiveTaskId: vi.fn(),
    cancelActive: vi.fn(),
    cancelling: false,
    submitInstruction,
    lastReply: null,
  } as unknown as ReturnType<typeof taskContext.useTask>);
  return render(
    <MemoryRouter>
      <MissionsPage />
    </MemoryRouter>,
  );
}

describe("MissionsPage for tasks MILO works out itself", () => {
  it("says it is working it out, with the user's own words as the title", () => {
    renderWith(task("novel", { source: "model", note: "I added the steps to go to things before using them." }));
    expect(screen.getByRole("heading", { name: "chill the apple" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("I don't know this one yet, so I'm working it out.");
    expect(screen.getByRole("status")).toHaveTextContent("I added the steps");
  });

  it("says when it is reusing a skill it learned", () => {
    renderWith(task("novel", { source: "skill" }));
    expect(screen.getByRole("status")).toHaveTextContent("I've done something like this before");
  });

  it("shows nothing extra for ordinary planners, and retrying never asks for the novel planner", () => {
    renderWith(task("htn", null));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    const submit = vi.fn();
    renderWith(task("novel", { source: "model" }, "failed"), submit);
    fireEvent.click(screen.getAllByRole("button", { name: "Try again" })[0]);
    expect(submit).toHaveBeenCalledWith("chill the apple", "text", undefined);
  });
});

describe("Save as skill", () => {
  it("is offered after a mission that worked and saves with the chosen name", async () => {
    const skillsApi = await import("../api/skills");
    const save = vi.spyOn(skillsApi, "saveTaskAsSkill").mockResolvedValue({
      skill_id: "s1",
      name: "chill",
      wording: "chill the {o0}",
      status: "candidate",
      successes: 1,
      failures: 0,
      success_rate: 1,
      last_used: null,
      steps: [],
    });
    renderWith(task("htn", null, "succeeded"));
    fireEvent.click(screen.getByRole("button", { name: "Save as skill" }));
    fireEvent.change(screen.getByLabelText("Skill name"), { target: { value: "chill" } });
    fireEvent.click(screen.getByRole("button", { name: "Save skill" }));
    expect(await screen.findByRole("status")).toHaveTextContent('Say "chill the …"');
    expect(save).toHaveBeenCalledWith("t1", "chill");
  });

  it("is not offered while the mission is running", () => {
    renderWith(task("htn", null, "executing"));
    expect(screen.queryByRole("button", { name: "Save as skill" })).not.toBeInTheDocument();
  });
});

describe("Undo and 'the other one'", () => {
  it("previews an undo, says what can't be undone, then starts it", async () => {
    const tasksApi = await import("../api/tasks");
    vi.spyOn(tasksApi, "undoPreview").mockResolvedValue({
      steps: [
        { action: "locate", target: "Fridge|1" },
        { action: "navigate", target: "Fridge|1" },
        { action: "close", target: "Fridge|1" },
      ],
      cannot_undo: ["push the egg"],
      possible: true,
    });
    const undo = vi.spyOn(tasksApi, "undoTask").mockResolvedValue({ task_id: "u1" } as never);
    const t = task("htn", null, "succeeded");
    renderWith(t);
    fireEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(await screen.findByText(/put things back with 1 actions/)).toHaveTextContent("I can't undo: push the egg.");
    fireEvent.click(screen.getByRole("button", { name: "Put it back" }));
    await vi.waitFor(() => expect(undo).toHaveBeenCalledWith("t1"));
  });

  it("offers 'No, the other one' for a pinned object", async () => {
    const tasksApi = await import("../api/tasks");
    const correct = vi.spyOn(tasksApi, "correctTask").mockResolvedValue({ task_id: "t2" } as never);
    renderWith({ ...task("rule_based", null, "executing"), objects: ["Cup|1"] });
    fireEvent.click(screen.getByRole("button", { name: "No, the other one" }));
    await vi.waitFor(() => expect(correct).toHaveBeenCalledWith("t1"));
  });

  it("shows MILO's question when it is waiting", () => {
    renderWith({
      ...task("rule_based", null, "executing"),
      pending_decision: { kind: "step", why: "the egg is fragile", text: "Pushing the egg." },
    });
    expect(screen.getByRole("alertdialog", { name: "MILO needs your OK" })).toBeInTheDocument();
  });
});

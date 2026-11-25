// MissionsPage.test.tsx -- the "working it out" notice for tasks MILO plans itself.
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { MissionsPage } from "./MissionsPage";
import * as taskContext from "../state/TaskContext";

vi.mock("../state/TaskContext", () => ({ useTask: vi.fn() }));

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

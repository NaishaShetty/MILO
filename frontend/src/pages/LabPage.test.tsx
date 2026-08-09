// LabPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LabPage } from "./LabPage";
import { AgentsProvider } from "../state/AgentsContext";
import { TaskProvider } from "../state/TaskContext";
import * as tasksApi from "../api/tasks";
import * as agentsApi from "../api/agents";

vi.mock("../api/tasks", async () => {
  const actual = await vi.importActual<typeof import("../api/tasks")>("../api/tasks");
  return {
    ...actual,
    listTasks: vi.fn(),
    getTask: vi.fn(),
    getTaskEvents: vi.fn(),
  };
});

vi.mock("../api/agents", async () => {
  const actual = await vi.importActual<typeof import("../api/agents")>("../api/agents");
  return { ...actual, listAgents: vi.fn() };
});

function renderPage() {
  return render(
    <MemoryRouter>
      <AgentsProvider>
        <TaskProvider>
          <LabPage />
        </TaskProvider>
      </AgentsProvider>
    </MemoryRouter>,
  );
}

function task(overrides: Record<string, unknown> = {}) {
  return {
    task_id: "t1",
    user_request: "find the mug",
    input_source: "text",
    goal: "find",
    objects: ["mug"],
    target: null,
    current_location: null,
    current_plan: { plan_id: "p1", task_id: "t1", planner_type: "rule_based", goal_summary: {}, status: "completed", created_at: 0, metadata: {}, steps: [] },
    current_step: null,
    observations: [],
    known_objects: [],
    completed_steps: [],
    execution_history: [],
    failures: [],
    retrieved_memories: [],
    agent_states: {},
    status: "succeeded",
    latencies_ms: {},
    created_memories: [{ memory_id: "m1", memory_type: "episodic" }],
    metrics: { actions: 3, failures: 1, replans: 1, attempts: 2, success: true, total_ms: 5000 },
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(tasksApi.listTasks).mockReset().mockResolvedValue([]);
  vi.mocked(tasksApi.getTask).mockReset();
  vi.mocked(tasksApi.getTaskEvents).mockReset().mockResolvedValue([]);
  vi.mocked(agentsApi.listAgents).mockReset().mockResolvedValue([]);
});

describe("LabPage", () => {
  it("shows zeroed real stats and no experiment framework claim when nothing has run", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Tasks run: 0")).toBeInTheDocument());
    expect(screen.getByText(/no experiment framework connected/i)).toBeInTheDocument();
    expect(screen.getByText("No active task.")).toBeInTheDocument();
  });

  it("computes real lab stats from task history", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([task() as never]);

    renderPage();

    expect(await screen.findByText("Tasks run: 1")).toBeInTheDocument();
    expect(screen.getByText("Success rate: 100%")).toBeInTheDocument();
    expect(screen.getByText("Total actions: 3")).toBeInTheDocument();
    expect(screen.getByText("Memories created: 1")).toBeInTheDocument();
    expect(screen.getByText("Failures: 1")).toBeInTheDocument();
    expect(screen.getByText("Replans: 1")).toBeInTheDocument();
    expect(screen.getByText("Average task time: 5.0 s")).toBeInTheDocument();
  });

  it("mirrors the active task in My Sandbox", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([task({ status: "executing" }) as never]);
    vi.mocked(tasksApi.getTask).mockResolvedValue(task({ status: "executing" }) as never);

    renderPage();

    const sandbox = await screen.findByRole("region", { name: "My Sandbox" });
    await waitFor(() => expect(sandbox).toHaveTextContent("find the mug"));
  });

  it("shows real agent status in Technical System Information", async () => {
    vi.mocked(agentsApi.listAgents).mockResolvedValue([{ name: "vision", state: "idle" }]);
    renderPage();
    const section = await screen.findByRole("region", { name: "Technical System Information" });
    await waitFor(() => expect(section).toHaveTextContent("Idle"));
  });
});

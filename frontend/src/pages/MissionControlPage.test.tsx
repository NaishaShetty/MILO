// MissionControlPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MissionControlPage } from "./MissionControlPage";
import { AgentsProvider } from "../state/AgentsContext";
import { SpeechProvider } from "../state/SpeechContext";
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
    createTask: vi.fn(),
    cancelTask: vi.fn(),
  };
});

vi.mock("../api/agents", async () => {
  const actual = await vi.importActual<typeof import("../api/agents")>("../api/agents");
  return { ...actual, listAgents: vi.fn() };
});

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/mission-control"]}>
      <AgentsProvider>
        <TaskProvider>
          <SpeechProvider>
            <MissionControlPage />
          </SpeechProvider>
        </TaskProvider>
      </AgentsProvider>
    </MemoryRouter>,
  );
}

function runningTask(overrides: Record<string, unknown> = {}) {
  return {
    task_id: "t1",
    user_request: "bring the red mug",
    input_source: "text",
    goal: "bring",
    objects: ["mug"],
    target: "user",
    current_location: "kitchen",
    current_plan: {
      plan_id: "p1",
      task_id: "t1",
      planner_type: "rule_based",
      goal_summary: {},
      status: "executing",
      created_at: 0,
      metadata: {},
      steps: [
        {
          step_id: 1,
          action: "navigate_to",
          target: "kitchen",
          parameters: {},
          description: "Navigate to kitchen",
          preconditions: [],
          postconditions: [],
          status: "completed",
        },
        {
          step_id: 2,
          action: "pick_up",
          target: "mug",
          parameters: {},
          description: "Pick up mug",
          preconditions: [],
          postconditions: [],
          status: "running",
        },
      ],
    },
    current_step: 2,
    observations: [],
    known_objects: ["mug"],
    completed_steps: [1],
    execution_history: [],
    failures: [],
    retrieved_memories: [],
    agent_states: {},
    status: "executing",
    latencies_ms: {},
    created_memories: [],
    metrics: { actions: 1, failures: 0, replans: 0, attempts: 1, success: false, total_ms: null },
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(tasksApi.listTasks).mockReset().mockResolvedValue([]);
  vi.mocked(tasksApi.getTask).mockReset();
  vi.mocked(tasksApi.getTaskEvents).mockReset().mockResolvedValue([]);
  vi.mocked(tasksApi.cancelTask).mockReset();
  vi.mocked(agentsApi.listAgents).mockReset().mockResolvedValue([
    { name: "vision", state: "active" },
    { name: "navigation", state: "idle" },
  ]);
});

describe("MissionControlPage", () => {
  it("shows 'No active mission' when nothing has run", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("No active mission.")).toBeInTheDocument());
  });

  it("shows the active task's request, status, and plan progress", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([runningTask() as never]);
    vi.mocked(tasksApi.getTask).mockResolvedValue(runningTask() as never);

    renderPage();

    expect(await screen.findByText("bring the red mug")).toBeInTheDocument();
    expect(screen.getByText("Status: executing")).toBeInTheDocument();
    expect(screen.getByText("Progress: 1/2 steps")).toBeInTheDocument();
  });

  it("renders the plan's steps", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([runningTask() as never]);
    vi.mocked(tasksApi.getTask).mockResolvedValue(runningTask() as never);

    renderPage();

    expect(await screen.findByText("Navigate to kitchen")).toBeInTheDocument();
    expect(screen.getByText("Pick up mug")).toBeInTheDocument();
  });

  it("renders real agent status, not a hardcoded value", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Active")).toBeInTheDocument());
  });

  it("shows location and target from the active task", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([runningTask() as never]);
    vi.mocked(tasksApi.getTask).mockResolvedValue(runningTask() as never);

    renderPage();

    expect(await screen.findByText("Location: kitchen — Target: user")).toBeInTheDocument();
  });

  it("renders activity feed events for the active task", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([runningTask() as never]);
    vi.mocked(tasksApi.getTask).mockResolvedValue(runningTask() as never);
    vi.mocked(tasksApi.getTaskEvents).mockResolvedValue([
      {
        event_id: "e1",
        task_id: "t1",
        agent: "planner",
        event: "PLAN_CREATED",
        timestamp: 1000,
        payload: {},
        latency_ms: null,
      },
    ] as never);

    renderPage();

    expect(await screen.findByText("PLAN_CREATED")).toBeInTheDocument();
  });

  it("cancels the active mission and reflects the cancelled state", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([runningTask() as never]);
    vi.mocked(tasksApi.getTask).mockResolvedValue(runningTask() as never);
    vi.mocked(tasksApi.cancelTask).mockResolvedValue(runningTask({ status: "cancelled" }) as never);

    const user = userEvent.setup();
    renderPage();

    const cancelButton = await screen.findByRole("button", { name: "Cancel Mission" });
    vi.mocked(tasksApi.getTask).mockResolvedValue(runningTask({ status: "cancelled" }) as never);
    await user.click(cancelButton);

    await waitFor(() => expect(tasksApi.cancelTask).toHaveBeenCalledWith("t1"));
    expect(await screen.findByText("Mission cancelled.")).toBeInTheDocument();
  });
});

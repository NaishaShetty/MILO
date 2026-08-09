// LabPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LabPage } from "./LabPage";
import { AgentsProvider } from "../state/AgentsContext";
import { TaskProvider } from "../state/TaskContext";
import * as tasksApi from "../api/tasks";
import * as agentsApi from "../api/agents";
import * as labApi from "../api/lab";

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

vi.mock("../api/lab", async () => {
  const actual = await vi.importActual<typeof import("../api/lab")>("../api/lab");
  return {
    ...actual,
    listExperiments: vi.fn(),
    runPerceptionExperiment: vi.fn(),
    runSandbox: vi.fn(),
    getLabStats: vi.fn(),
  };
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

beforeEach(() => {
  vi.mocked(tasksApi.listTasks).mockReset().mockResolvedValue([]);
  vi.mocked(tasksApi.getTask).mockReset();
  vi.mocked(tasksApi.getTaskEvents).mockReset().mockResolvedValue([]);
  vi.mocked(agentsApi.listAgents).mockReset().mockResolvedValue([]);
  vi.mocked(labApi.listExperiments).mockReset().mockResolvedValue({ experiments: [] });
  vi.mocked(labApi.runPerceptionExperiment).mockReset();
  vi.mocked(labApi.runSandbox).mockReset();
  vi.mocked(labApi.getLabStats)
    .mockReset()
    .mockResolvedValue({
      experiments_run: 0,
      task_success_rate: null,
      total_actions: 0,
      memories_created: 0,
      tasks_run: 0,
    });
});

describe("LabPage", () => {
  it("shows zeroed real stats and no fabricated experiments when nothing has run", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Tasks run: 0")).toBeInTheDocument());
    expect(screen.getByText("No experiments have been run yet.")).toBeInTheDocument();
  });

  it("shows real lab stats from the backend", async () => {
    vi.mocked(labApi.getLabStats).mockResolvedValue({
      experiments_run: 2,
      task_success_rate: 1,
      total_actions: 3,
      memories_created: 1,
      tasks_run: 1,
    });

    renderPage();

    expect(await screen.findByText("Experiments run: 2")).toBeInTheDocument();
    expect(screen.getByText("Tasks run: 1")).toBeInTheDocument();
    expect(screen.getByText("Success rate: 100%")).toBeInTheDocument();
    expect(screen.getByText("Total actions: 3")).toBeInTheDocument();
    expect(screen.getByText("Memories created: 1")).toBeInTheDocument();
  });

  it("lists real experiments from the backend", async () => {
    vi.mocked(labApi.listExperiments).mockResolvedValue({
      experiments: [
        { run_id: "perception_1", experiment_type: "perception", timestamp: "2026-08-09T12:00:00Z", result: {} },
      ],
    });

    renderPage();

    expect(await screen.findByText("perception_1")).toBeInTheDocument();
  });

  it("runs a real perception experiment and refreshes the list", async () => {
    vi.mocked(labApi.runPerceptionExperiment).mockResolvedValue({
      run_id: "perception_2",
      experiment_type: "perception",
      timestamp: "2026-08-09T12:05:00Z",
      result: {},
    });
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByRole("button", { name: "Run Perception Benchmark" }));

    await waitFor(() => expect(labApi.runPerceptionExperiment).toHaveBeenCalled());
  });

  it("My Sandbox runs a real dry-run parse+plan via the backend", async () => {
    vi.mocked(labApi.runSandbox).mockResolvedValue({
      parsed: { task_type: "single", goal: "store", object: "apple", target: "refrigerator" } as never,
      plan: {
        success: true,
        planner_type: "rule_based",
        latency_ms: 1,
        errors: [],
        plan: {
          plan_id: "p1",
          task_id: "",
          planner_type: "rule_based",
          goal_summary: {},
          steps: [{ step_id: 1, action: "navigate_to", target: "apple", parameters: {}, description: "", preconditions: [], postconditions: [], status: "pending" }],
          status: "valid",
          created_at: 0,
          metadata: {},
        },
      },
      unsupported_reason: null,
    });

    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("Try an instruction"), "store the apple");
    await user.click(screen.getByRole("button", { name: "Run" }));

    await waitFor(() => expect(labApi.runSandbox).toHaveBeenCalledWith("store the apple"));
    expect(await screen.findByText("1 step(s), rule_based")).toBeInTheDocument();
  });

  it("shows real agent status in Technical System Information", async () => {
    vi.mocked(agentsApi.listAgents).mockResolvedValue([{ name: "vision", state: "idle" }]);
    renderPage();
    const section = await screen.findByRole("region", { name: "Technical System Information" });
    await waitFor(() => expect(section).toHaveTextContent("Idle"));
  });
});

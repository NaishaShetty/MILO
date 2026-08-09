// ActivityPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ActivityPage } from "./ActivityPage";
import { TaskProvider } from "../state/TaskContext";
import * as tasksApi from "../api/tasks";

vi.mock("../api/tasks", async () => {
  const actual = await vi.importActual<typeof import("../api/tasks")>("../api/tasks");
  return {
    ...actual,
    listTasks: vi.fn(),
    getTask: vi.fn(),
    getTaskEvents: vi.fn(),
    createTask: vi.fn(),
  };
});

function renderPage() {
  return render(
    <MemoryRouter>
      <TaskProvider>
        <ActivityPage />
      </TaskProvider>
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
    current_plan: null,
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
    created_memories: [],
    metrics: { actions: 0, failures: 0, replans: 0, attempts: 0, success: true, total_ms: null },
    ...overrides,
  };
}

function evt(overrides: Record<string, unknown> = {}) {
  return {
    event_id: "e1",
    task_id: "t1",
    agent: "orchestrator",
    event: "TASK_CREATED",
    timestamp: 1000,
    payload: {},
    latency_ms: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(tasksApi.listTasks).mockReset().mockResolvedValue([]);
  vi.mocked(tasksApi.getTask).mockReset();
  vi.mocked(tasksApi.getTaskEvents).mockReset().mockResolvedValue([]);
  vi.mocked(tasksApi.createTask).mockReset();
});

describe("ActivityPage", () => {
  it("shows an empty state when there is no activity", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("No activity yet.")).toBeInTheDocument());
  });

  it("renders merged events from the task history", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([task() as never]);
    vi.mocked(tasksApi.getTaskEvents).mockResolvedValue([
      evt({ event_id: "e1", event: "TASK_CREATED" }),
      evt({ event_id: "e2", event: "PLAN_CREATED" }),
    ] as never);

    renderPage();

    expect(await screen.findByText("TASK_CREATED")).toBeInTheDocument();
    expect(screen.getByText("PLAN_CREATED")).toBeInTheDocument();
  });

  it("filters events by category", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([task() as never]);
    vi.mocked(tasksApi.getTaskEvents).mockResolvedValue([
      evt({ event_id: "e1", event: "TASK_CREATED" }),
      evt({ event_id: "e2", event: "PLAN_CREATED" }),
    ] as never);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("TASK_CREATED");

    await user.click(screen.getByRole("button", { name: "Planning" }));

    expect(screen.queryByText("TASK_CREATED")).not.toBeInTheDocument();
    expect(screen.getByText("PLAN_CREATED")).toBeInTheDocument();
  });

  it("searches loaded events by text", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([task() as never]);
    vi.mocked(tasksApi.getTaskEvents).mockResolvedValue([
      evt({ event_id: "e1", event: "TASK_CREATED" }),
      evt({ event_id: "e2", event: "PLAN_CREATED" }),
    ] as never);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("TASK_CREATED");

    await user.type(screen.getByLabelText("Search activity"), "plan");

    expect(screen.queryByText("TASK_CREATED")).not.toBeInTheDocument();
    expect(screen.getByText("PLAN_CREATED")).toBeInTheDocument();
  });

  it("shows event details when an event is selected", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([task() as never]);
    vi.mocked(tasksApi.getTaskEvents).mockResolvedValue([
      evt({ event_id: "e1", event: "TASK_CREATED", agent: "orchestrator", payload: { goal: "find" } }),
    ] as never);
    const user = userEvent.setup();
    renderPage();

    await user.click(await screen.findByText("TASK_CREATED"));

    const details = screen.getByRole("region", { name: "Event Details" });
    expect(details).toHaveTextContent("orchestrator");
    expect(details).toHaveTextContent("find");
  });

  it("disables Export Log when there is nothing to export", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByRole("button", { name: "Export Log" })).toBeDisabled());
  });
});

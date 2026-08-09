// MemoryPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MemoryPage } from "./MemoryPage";
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
        <MemoryPage />
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

beforeEach(() => {
  vi.mocked(tasksApi.listTasks).mockReset().mockResolvedValue([]);
  vi.mocked(tasksApi.getTask).mockReset();
  vi.mocked(tasksApi.getTaskEvents).mockReset().mockResolvedValue([]);
  vi.mocked(tasksApi.createTask).mockReset();
});

describe("MemoryPage", () => {
  it("shows all four categories with a real (zero) count when nothing has run", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Things I Know")).toBeInTheDocument());
    expect(screen.getByText("Experiences")).toBeInTheDocument();
    expect(screen.getByText("Things That Went Wrong")).toBeInTheDocument();
    expect(screen.getByText("Your Preferences")).toBeInTheDocument();
    expect(screen.getByText("No memories yet.")).toBeInTheDocument();
  });

  it("shows real category counts, recent memories, and statistics once tasks have memories", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([
      task({
        created_memories: [
          { memory_id: "m1", memory_type: "semantic", content: "Kitchen has a fridge" },
        ],
        retrieved_memories: [
          { memory_id: "m2", memory_type: "failure", content: "Could not find the mug" },
        ],
      }) as never,
    ]);

    renderPage();

    expect((await screen.findAllByText("Kitchen has a fridge")).length).toBeGreaterThan(0);
    expect(screen.getByText("Could not find the mug")).toBeInTheDocument();
    expect(screen.getByText("Semantic: 1")).toBeInTheDocument();
    expect(screen.getByText("Failures: 1")).toBeInTheDocument();
  });

  it("lists semantic memories under My Knowledge", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([
      task({
        created_memories: [{ memory_id: "m1", memory_type: "semantic", content: "Kitchen has a fridge" }],
      }) as never,
    ]);

    renderPage();

    const knowledgeSection = screen.getByRole("region", { name: "My Knowledge" });
    await waitFor(() => expect(knowledgeSection).toHaveTextContent("Kitchen has a fridge"));
  });

  it("Quick Memory Search asks a real question via submitInstruction and shows the result", async () => {
    vi.mocked(tasksApi.createTask).mockResolvedValue(
      task({
        task_id: "t2",
        status: "succeeded",
        retrieved_memories: [{ memory_id: "m9", content: "Last seen on the dining table." }],
      }) as never,
    );
    vi.mocked(tasksApi.getTask).mockResolvedValue(
      task({
        task_id: "t2",
        status: "succeeded",
        retrieved_memories: [{ memory_id: "m9", content: "Last seen on the dining table." }],
      }) as never,
    );

    const user = userEvent.setup();
    renderPage();

    await user.type(
      screen.getByLabelText("Ask MILO about its memory"),
      "Where did you last see the mug?",
    );
    await user.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() =>
      expect(tasksApi.createTask).toHaveBeenCalledWith("Where did you last see the mug?", "text"),
    );
    expect(await screen.findByText("Last seen on the dining table.")).toBeInTheDocument();
  });

  it("shows a memory timeline entry per aggregated memory", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([
      task({ created_memories: [{ memory_id: "m1", memory_type: "episodic", content: "picked up mug" }] }) as never,
    ]);

    renderPage();

    expect(await screen.findByText(/Task t1: created a episodic memory/)).toBeInTheDocument();
  });
});

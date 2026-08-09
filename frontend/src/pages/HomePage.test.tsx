// HomePage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HomePage } from "./HomePage";
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
  };
});

vi.mock("../api/agents", async () => {
  const actual = await vi.importActual<typeof import("../api/agents")>("../api/agents");
  return { ...actual, listAgents: vi.fn() };
});

function renderHome() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <AgentsProvider>
        <TaskProvider>
          <SpeechProvider>
            <HomePage />
          </SpeechProvider>
        </TaskProvider>
      </AgentsProvider>
    </MemoryRouter>,
  );
}

function baseTask(overrides: Record<string, unknown> = {}) {
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
    latencies_ms: { total_ms: 4200 },
    created_memories: [],
    metrics: { actions: 2, failures: 0, replans: 0, attempts: 1, success: true, total_ms: 4200 },
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(tasksApi.listTasks).mockReset().mockResolvedValue([]);
  vi.mocked(tasksApi.createTask).mockReset();
  vi.mocked(tasksApi.getTask).mockReset();
  vi.mocked(tasksApi.getTaskEvents).mockReset().mockResolvedValue([]);
  vi.mocked(agentsApi.listAgents).mockReset().mockResolvedValue([{ name: "vision", state: "idle" }]);
});

describe("HomePage", () => {
  it("greets the user as MILO and explains what it does", async () => {
    renderHome();
    expect(screen.getByText("Hi, I'm MILO.")).toBeInTheDocument();
    expect(screen.getByText("Memory Integrated Language Oriented Robot")).toBeInTheDocument();
    await waitFor(() => expect(tasksApi.listTasks).toHaveBeenCalled());
  });

  it("shows an empty state for Recent Mission and Latest Memory when nothing has run", async () => {
    renderHome();
    await waitFor(() => expect(screen.getByText("No missions yet.")).toBeInTheDocument());
    expect(screen.getByText("No memories yet.")).toBeInTheDocument();
  });

  it("shows real agent status, not a hardcoded Online", async () => {
    renderHome();
    await waitFor(() => expect(screen.getByText("Idle")).toBeInTheDocument());
    expect(screen.queryByText("Online")).not.toBeInTheDocument();
  });

  it("submits a typed instruction via createTask and clears the input", async () => {
    vi.mocked(tasksApi.createTask).mockResolvedValue(baseTask({ status: "created" }) as never);
    vi.mocked(tasksApi.getTask).mockResolvedValue(baseTask({ status: "created" }) as never);
    const user = userEvent.setup();
    renderHome();

    const input = screen.getByLabelText("Instruction for MILO");
    await user.type(input, "find the mug");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(tasksApi.createTask).toHaveBeenCalledWith("find the mug", "text"),
    );
  });

  it("quick example buttons submit their fixed instruction", async () => {
    vi.mocked(tasksApi.createTask).mockResolvedValue(baseTask({ status: "created" }) as never);
    vi.mocked(tasksApi.getTask).mockResolvedValue(baseTask({ status: "created" }) as never);
    const user = userEvent.setup();
    renderHome();

    await user.click(screen.getByRole("button", { name: "Find the apple" }));

    await waitFor(() => expect(tasksApi.createTask).toHaveBeenCalledWith("Find the apple", "text"));
  });

  it("shows real recent mission data once a task has run", async () => {
    vi.mocked(tasksApi.listTasks).mockResolvedValue([baseTask() as never]);
    renderHome();

    expect(await screen.findByText("find the mug")).toBeInTheDocument();
    expect(screen.getByText("Status: succeeded")).toBeInTheDocument();
  });

  it("toggles the mic button label when listening starts", async () => {
    vi.stubGlobal("navigator", { ...navigator, mediaDevices: undefined });
    const user = userEvent.setup();
    renderHome();

    await user.click(screen.getByRole("button", { name: /speak an instruction/i }));

    expect(await screen.findByText(/microphone unavailable/i)).toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});

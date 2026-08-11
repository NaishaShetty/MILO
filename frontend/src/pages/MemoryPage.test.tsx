// MemoryPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MemoryPage } from "./MemoryPage";
import * as memoryApi from "../api/memory";
import type { Memory } from "../api/memoryTypes";
import { AgentsProvider } from "../state/AgentsContext";
import { MiloStateProvider } from "../state/MiloStateContext";
import { SpeechProvider } from "../state/SpeechContext";
import { TaskProvider } from "../state/TaskContext";
import { VoiceProvider } from "../state/VoiceContext";

vi.mock("../api/memory", async () => {
  const actual = await vi.importActual<typeof import("../api/memory")>("../api/memory");
  return { ...actual, listMemory: vi.fn(), searchMemory: vi.fn() };
});

vi.mock("../api/tasks", async () => {
  const actual = await vi.importActual<typeof import("../api/tasks")>("../api/tasks");
  return {
    ...actual,
    listTasks: vi.fn().mockResolvedValue([]),
    getTask: vi.fn(),
    getTaskEvents: vi.fn(),
    createTask: vi.fn(),
  };
});

vi.mock("../api/agents", async () => {
  const actual = await vi.importActual<typeof import("../api/agents")>("../api/agents");
  return { ...actual, listAgents: vi.fn().mockResolvedValue([]) };
});

vi.mock("../api/voice", async () => {
  const actual = await vi.importActual<typeof import("../api/voice")>("../api/voice");
  return { ...actual, speak: vi.fn() };
});

function renderPage() {
  return render(
    <MemoryRouter>
      <AgentsProvider>
        <TaskProvider>
          <SpeechProvider>
            <VoiceProvider>
              <MiloStateProvider>
                <MemoryPage />
              </MiloStateProvider>
            </VoiceProvider>
          </SpeechProvider>
        </TaskProvider>
      </AgentsProvider>
    </MemoryRouter>,
  );
}

function memory(overrides: Partial<Memory> = {}): Memory {
  return {
    memory_id: "m1",
    memory_type: "semantic",
    content: "Kitchen has a fridge",
    provenance: "observation",
    status: "active",
    confidence: 1,
    created_at: 1700000000,
    observed_at: null,
    updated_at: 1700000000,
    episode_id: null,
    task_id: "t1",
    metadata: {},
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(memoryApi.listMemory)
    .mockReset()
    .mockResolvedValue({ memories: [], counts_by_type: { semantic: 0, episodic: 0, failure: 0, user: 0 } });
  vi.mocked(memoryApi.searchMemory).mockReset();
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

  it("shows real category counts, recent memories, and statistics once memories exist", async () => {
    vi.mocked(memoryApi.listMemory).mockResolvedValue({
      memories: [
        memory({ memory_id: "m1", memory_type: "semantic", content: "Kitchen has a fridge" }),
        memory({ memory_id: "m2", memory_type: "failure", content: "Could not find the mug" }),
      ],
      counts_by_type: { semantic: 1, episodic: 0, failure: 1, user: 0 },
    });

    renderPage();

    expect((await screen.findAllByText("Kitchen has a fridge")).length).toBeGreaterThan(0);
    expect(screen.getByText("Could not find the mug")).toBeInTheDocument();
    expect(screen.getByText("Semantic: 1")).toBeInTheDocument();
    expect(screen.getByText("Failures: 1")).toBeInTheDocument();
  });

  it("lists semantic memories under My Knowledge", async () => {
    vi.mocked(memoryApi.listMemory).mockResolvedValue({
      memories: [memory({ memory_id: "m1", memory_type: "semantic", content: "Kitchen has a fridge" })],
      counts_by_type: { semantic: 1, episodic: 0, failure: 0, user: 0 },
    });

    renderPage();

    const knowledgeSection = screen.getByRole("region", { name: "My Knowledge" });
    await waitFor(() => expect(knowledgeSection).toHaveTextContent("Kitchen has a fridge"));
  });

  it("Quick Memory Search queries the real memory search endpoint and shows the result", async () => {
    vi.mocked(memoryApi.searchMemory).mockResolvedValue({
      query: "Where did you last see the mug?",
      results: [
        {
          memory: memory({ memory_id: "m9", content: "Last seen on the dining table." }),
          similarity: 0.9,
          final_score: 0.9,
          ranking_components: {},
        },
      ],
    });

    const user = userEvent.setup();
    renderPage();

    await user.type(
      screen.getByLabelText("Ask MILO about its memory"),
      "Where did you last see the mug?",
    );
    await user.click(screen.getByRole("button", { name: "Ask" }));

    await waitFor(() =>
      expect(memoryApi.searchMemory).toHaveBeenCalledWith("Where did you last see the mug?"),
    );
    expect(await screen.findByText("Last seen on the dining table.")).toBeInTheDocument();
  });

  it("shows a memory timeline entry per real memory", async () => {
    vi.mocked(memoryApi.listMemory).mockResolvedValue({
      memories: [memory({ memory_id: "m1", memory_type: "episodic", content: "picked up mug" })],
      counts_by_type: { semantic: 0, episodic: 1, failure: 0, user: 0 },
    });

    renderPage();

    expect(await screen.findByText(/observation created a episodic memory/)).toBeInTheDocument();
  });
});

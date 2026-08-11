// AboutPage.test.tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { AboutPage } from "./AboutPage";
import { AgentsProvider } from "../state/AgentsContext";
import { MiloStateProvider } from "../state/MiloStateContext";
import { SpeechProvider } from "../state/SpeechContext";
import { TaskProvider } from "../state/TaskContext";
import { VoiceProvider } from "../state/VoiceContext";

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
                <AboutPage />
              </MiloStateProvider>
            </VoiceProvider>
          </SpeechProvider>
        </TaskProvider>
      </AgentsProvider>
    </MemoryRouter>,
  );
}

describe("AboutPage", () => {
  it("greets the user as MILO with its full name", () => {
    renderPage();
    expect(screen.getByText("Hi, I'm MILO.")).toBeInTheDocument();
    expect(screen.getByText("Memory Integrated Language Oriented Robot")).toBeInTheDocument();
  });

  it("explains every stage of the MILO pipeline", () => {
    renderPage();
    for (const stage of [
      "Perceive",
      "Understand",
      "Remember",
      "Plan",
      "Navigate",
      "Act",
      "Reflect",
      "Replan",
      "Learn",
    ]) {
      expect(screen.getByText(stage)).toBeInTheDocument();
    }
  });

  it("links to Home, Mission Control, and MILO Lab", () => {
    renderPage();
    expect(screen.getByRole("link", { name: "Home" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Mission Control" })).toHaveAttribute(
      "href",
      "/mission-control",
    );
    expect(screen.getByRole("link", { name: "MILO Lab" })).toHaveAttribute("href", "/lab");
  });
});

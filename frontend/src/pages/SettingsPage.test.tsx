// SettingsPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SettingsPage } from "./SettingsPage";
import { SettingsProvider } from "../state/SettingsContext";
import { TaskProvider } from "../state/TaskContext";
import * as tasksApi from "../api/tasks";
import * as voiceApi from "../api/voice";

vi.mock("../api/tasks", async () => {
  const actual = await vi.importActual<typeof import("../api/tasks")>("../api/tasks");
  return { ...actual, listTasks: vi.fn(), getTask: vi.fn(), getTaskEvents: vi.fn() };
});

vi.mock("../api/voice", async () => {
  const actual = await vi.importActual<typeof import("../api/voice")>("../api/voice");
  return { ...actual, getVoiceStatus: vi.fn() };
});

function renderPage() {
  return render(
    <MemoryRouter>
      <SettingsProvider>
        <TaskProvider>
          <SettingsPage />
        </TaskProvider>
      </SettingsProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  vi.mocked(tasksApi.listTasks).mockReset().mockResolvedValue([]);
  vi.mocked(tasksApi.getTaskEvents).mockReset().mockResolvedValue([]);
  vi.mocked(voiceApi.getVoiceStatus)
    .mockReset()
    .mockResolvedValue({ enabled: false, available: false, provider: "elevenlabs", voice_id: "ISnQja0Ank6t1FE2Wj07" });
  document.documentElement.removeAttribute("data-theme");
});

describe("SettingsPage", () => {
  it("renders all nine settings categories", async () => {
    renderPage();
    for (const name of [
      "General",
      "MILO Personality",
      "Speech & Voice",
      "Vision",
      "Memory",
      "Planning & Execution",
      "Notifications",
      "Data & Privacy",
      "Integrations",
      "About",
    ]) {
      expect(screen.getByRole("region", { name })).toBeInTheDocument();
    }
  });

  it("persists a nickname change to localStorage and reflects it live", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.type(screen.getByLabelText("Nickname for MILO"), "Robo");

    await waitFor(() => {
      const stored = JSON.parse(window.localStorage.getItem("milo:settings")!);
      expect(stored.general.nickname).toBe("Robo");
    });
    expect(screen.getByRole("region", { name: "MILO Personality" })).toHaveTextContent("Robo");
  });

  it("changing the theme applies it to the document root", async () => {
    const user = userEvent.setup();
    renderPage();

    await user.selectOptions(screen.getByLabelText("Theme"), "light");

    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
  });

  it("clears local settings without claiming to touch backend data", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByLabelText("Nickname for MILO"), "Robo");

    await user.click(screen.getByRole("button", { name: "Clear local settings" }));

    expect(window.localStorage.getItem("milo:settings")).toBeNull();
    expect(screen.getByText("Local settings cleared.")).toBeInTheDocument();
  });

  it("does not claim any external integrations exist", () => {
    renderPage();
    expect(screen.getByText("No external integrations configured.")).toBeInTheDocument();
  });

  it("labels Vision/Memory/Planning sections as read-only", () => {
    renderPage();
    expect(screen.getAllByText(/read-only/i).length).toBeGreaterThanOrEqual(3);
  });
});

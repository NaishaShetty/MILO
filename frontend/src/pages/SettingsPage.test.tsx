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
import * as languageApi from "../api/language";
import * as speechApi from "../api/speech";

vi.mock("../api/tasks", async () => {
  const actual = await vi.importActual<typeof import("../api/tasks")>("../api/tasks");
  return { ...actual, listTasks: vi.fn(), getTask: vi.fn(), getTaskEvents: vi.fn() };
});

vi.mock("../api/voice", async () => {
  const actual = await vi.importActual<typeof import("../api/voice")>("../api/voice");
  return { ...actual, getVoiceStatus: vi.fn() };
});

vi.mock("../api/language", async () => {
  const actual = await vi.importActual<typeof import("../api/language")>("../api/language");
  return { ...actual, getLanguageStatus: vi.fn() };
});

vi.mock("../api/speech", async () => {
  const actual = await vi.importActual<typeof import("../api/speech")>("../api/speech");
  return { ...actual, getSpeechStatus: vi.fn() };
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
  vi.mocked(languageApi.getLanguageStatus)
    .mockReset()
    .mockResolvedValue({ provider: "openai", model: "gpt-4o-mini", configured: false, available: false });
  vi.mocked(speechApi.getSpeechStatus)
    .mockReset()
    .mockResolvedValue({ provider: "whisper", enabled: false, available: false });
  document.documentElement.removeAttribute("data-theme");
});

describe("SettingsPage", () => {
  it("renders all ten settings categories", async () => {
    renderPage();
    for (const name of [
      "General",
      "MILO Personality",
      "Speech & Voice",
      "LLM Provider",
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

  it("shows the real LLM provider status without exposing a key", async () => {
    vi.mocked(languageApi.getLanguageStatus).mockResolvedValue({
      provider: "gemini",
      model: "gemini-flash-latest",
      configured: true,
      available: true,
    });
    renderPage();

    await waitFor(() => expect(screen.getByText(/gemini/i)).toBeInTheDocument());
    expect(screen.getByText(/Connected/i)).toBeInTheDocument();
    expect(screen.queryByText(/sk-|api[_-]?key/i)).not.toBeInTheDocument();
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

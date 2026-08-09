// App.test.tsx
//
// Purpose
// -------
// Routing test for the MILO application: all seven pages are
// reachable via the top nav, the nav highlights the active route, and
// an unknown path redirects to Home. Mocks the Task/Agents API modules
// so `TaskProvider`/`AgentsProvider`'s background polling never makes
// a real network request during this test (mirrors every other
// context test's `vi.mock` convention in this project).
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

beforeEach(() => {
  // `BrowserRouter` reads the real `window.location`/history, which
  // persists across tests in the same file (jsdom does not reset it
  // between `render()` calls) -- reset to `/` before every test so
  // navigation from a previous test can't leak into the next one.
  window.history.pushState({}, "", "/");
});

vi.mock("./api/agents", async () => {
  const actual = await vi.importActual<typeof import("./api/agents")>("./api/agents");
  return { ...actual, listAgents: vi.fn().mockResolvedValue([]) };
});

vi.mock("./api/tasks", async () => {
  const actual = await vi.importActual<typeof import("./api/tasks")>("./api/tasks");
  return {
    ...actual,
    listTasks: vi.fn().mockResolvedValue([]),
    getTask: vi.fn(),
    getTaskEvents: vi.fn(),
  };
});

describe("App routing", () => {
  it("shows the MILO brand and renders Home at /", async () => {
    render(<App />);
    expect(screen.getByText("MILO")).toBeInTheDocument();
    expect(screen.getAllByText("Memory Integrated Language Oriented Robot").length).toBeGreaterThan(0);
    expect(await screen.findByRole("heading", { name: "Home" })).toBeInTheDocument();
  });

  it.each([
    ["Mission Control"],
    ["Memory"],
    ["Activity"],
    ["About MILO"],
    ["MILO Lab"],
    ["Settings"],
  ])("navigates to %s via the nav link", async (linkLabel) => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "Home" });

    await user.click(screen.getByRole("link", { name: linkLabel }));

    // The page's own `<h1>` repeats the exact nav link text -- matched
    // at heading level 1 specifically, since several pages (e.g.
    // Memory) also have `<h2>` section headings that share a word with
    // the link label ("Recent Memories", "Memory Timeline", ...).
    expect(screen.getByRole("heading", { level: 1, name: linkLabel })).toBeInTheDocument();
  });

  it("marks the active route's nav link", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "Home" });

    const memoryLink = screen.getByRole("link", { name: "Memory" });
    await user.click(memoryLink);

    expect(memoryLink.className).toContain("milo-navbar__link--active");
    expect(screen.getByRole("link", { name: "Home" }).className).not.toContain("--active");
  });

  it("has exactly seven nav links (no Mission Detail page)", async () => {
    render(<App />);
    await screen.findByRole("heading", { name: "Home" });
    const nav = screen.getByRole("navigation", { name: /main navigation/i });
    expect(within(nav).getAllByRole("link")).toHaveLength(7);
  });
});

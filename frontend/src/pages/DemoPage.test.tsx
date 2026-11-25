// DemoPage.test.tsx -- demo mode replays recorded missions with no backend.
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DemoPage } from "./DemoPage";
import { isDemo } from "../api/demo";
import { getTrace, listTraces } from "../api/observability";

const missions = [
  { id: "m1", title: "Working out a new task", about: "Chill the apple.", outcome: "succeeded", task_text: "chill the apple" },
];

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
  window.history.replaceState({}, "", "/");
});

describe("demo mode", () => {
  it("turns on with ?demo=1, is remembered, and turns off with ?demo=0", () => {
    window.history.replaceState({}, "", "/?demo=1");
    expect(isDemo()).toBe(true);
    window.history.replaceState({}, "", "/");
    expect(isDemo()).toBe(true);
    window.history.replaceState({}, "", "/?demo=0");
    expect(isDemo()).toBe(false);
  });

  it("lists the recorded missions with links to their replays", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(missions), { status: 200 }));
    render(
      <MemoryRouter>
        <DemoPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Working out a new task")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Watch the replay" })).toHaveAttribute("href", "/replay/m1");
  });

  it("reads traces from the recorded files, never the API, in demo mode", async () => {
    window.localStorage.setItem("milo.demo", "1");
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (url) =>
        new Response(JSON.stringify(String(url).includes("missions") ? missions : { mission: { mission_id: "m1" }, records: [] }), { status: 200 }),
      );
    expect((await listTraces())[0].mission_id).toBe("m1");
    await getTrace("m1");
    const urls = fetchSpy.mock.calls.map((c) => String(c[0]));
    expect(urls).toEqual(["/demo/missions.json", "/demo/traces/m1.json"]);
  });
});

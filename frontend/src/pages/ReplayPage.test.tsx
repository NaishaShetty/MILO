// ReplayPage.test.tsx -- scrub through a mission; copy link; download report.
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { ReplayPage } from "./ReplayPage";
import { ObservabilityPanel } from "../components/ObservabilityPanel";
import { SceneMap } from "../components/SceneMap";
import * as api from "../api/observability";

vi.mock("../api/observability", async () => ({
  ...(await vi.importActual<object>("../api/observability")),
  getTrace: vi.fn(),
  listTraces: vi.fn(),
  downloadReport: vi.fn(),
  getTraceStats: vi.fn(),
  getWaterfall: vi.fn(),
  getSceneMap: vi.fn(),
}));

const trace = {
  mission: { mission_id: "m1", task_text: "put the apple in the fridge", planner: "rule_based", started_at: 0, ended_at: 1, outcome: "succeeded" },
  records: [
    { seq: 0, ts: 0, kind: "mission_started", step_id: null, data: {} },
    { seq: 1, ts: 0.1, kind: "plan", step_id: null, data: { plan: { steps: [{ step_id: 1, action: "open", target: "fridge" }, { step_id: 2, action: "pickup", target: "apple" }] } } },
    { seq: 2, ts: 0.2, kind: "step", step_id: 1, data: { action: "open", target: "fridge", status: "success", duration_ms: 12, frame: "AAAA" } },
    { seq: 3, ts: 0.3, kind: "thought", step_id: 1, data: { text: "The fridge is open." } },
    { seq: 4, ts: 0.4, kind: "step", step_id: 2, data: { action: "pickup", target: "apple", status: "success", duration_ms: 8 } },
    { seq: 5, ts: 0.5, kind: "reflection", step_id: null, data: { verdict: "continue", reason: "all steps done" } },
  ],
};

describe("ReplayPage", () => {
  it("scrubs through the mission showing the frame, step, thoughts and verdict", async () => {
    vi.mocked(api.getTrace).mockResolvedValue(trace);
    render(
      <MemoryRouter initialEntries={["/replay/m1"]}>
        <Routes>
          <Route path="/replay/:missionId" element={<ReplayPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText(/Replay: put the apple in the fridge/)).toBeInTheDocument();
    expect(screen.getByText(/Reflection:/)).toHaveTextContent("continue");
    fireEvent.change(screen.getByLabelText(/Moment/), { target: { value: "2" } });
    expect(screen.getByRole("img", { name: "MILO's camera at this moment" })).toHaveAttribute("src", "data:image/jpeg;base64,AAAA");
    expect(screen.getByText(/Step 1: success in 12 ms/)).toBeInTheDocument();
    expect(screen.queryByText(/Reflection:/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Download report" }));
    expect(api.downloadReport).toHaveBeenCalledWith("m1");
  });

  it("lists missions when none is chosen", async () => {
    vi.mocked(api.listTraces).mockResolvedValue([trace.mission]);
    render(
      <MemoryRouter initialEntries={["/replay"]}>
        <Routes>
          <Route path="/replay" element={<ReplayPage />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByRole("link", { name: "put the apple in the fridge" })).toHaveAttribute("href", "/replay/m1");
  });
});

describe("ObservabilityPanel and SceneMap", () => {
  it("shows p50/p95 per stage and a waterfall", async () => {
    vi.mocked(api.getTraceStats).mockResolvedValue({
      missions: 4,
      stages: { planning_ms: { p50: 3, p95: 9, n: 4 }, total_ms: { p50: 1500, p95: 2500, n: 4 }, vision_ms: { p50: null, p95: null, n: 0 } },
      actions: {},
    });
    vi.mocked(api.listTraces).mockResolvedValue([trace.mission]);
    vi.mocked(api.getWaterfall).mockResolvedValue([{ label: "open fridge", kind: "step", status: "failed", start_ms: 10, ms: 40 }]);
    render(<ObservabilityPanel />);
    const table = await screen.findByRole("table", { name: "Stage timings" });
    expect(table).toHaveTextContent("Planning3 ms9 ms");
    expect(table).toHaveTextContent("Whole mission1.5 s2.5 s");
    expect(table).not.toHaveTextContent("Looking");
    expect(await screen.findByRole("listitem")).toHaveTextContent("open fridge");
  });

  it("draws the room when there are positions and lists beliefs", async () => {
    vi.mocked(api.getSceneMap).mockResolvedValue({
      agent: { x: 0, z: 0 },
      path: [{ x: 0, z: 0, yaw: 0 }, { x: 1, z: 1, yaw: 90 }],
      objects: [{ id: "Mug|1", type: "mug", x: 1, z: 2, visible: true, in: ["table"] }],
      beliefs: [{ object: "mug", place: "table", confidence: 0.9, last_seen: Date.now() / 1000, source: "observation" }],
      has_positions: true,
    });
    render(<SceneMap live={false} />);
    expect(await screen.findByRole("img", { name: "Top-down map" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Memory beliefs" })).toHaveTextContent("90% sure · I saw it, last seen");
  });
});

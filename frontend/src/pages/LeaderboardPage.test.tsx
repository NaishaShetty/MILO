// LeaderboardPage.test.tsx
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LeaderboardPage } from "./LeaderboardPage";

const planner = (known: number | null, novel: number | null, faults: number | null) => ({
  known: { success: known },
  novel: { success: novel },
  faults: { success: faults },
  all: { steps: 7.8, sim_s: 11.7, replans: 0.14 },
  recovery_by_fault: { blocked_path: 1, out_of_reach: 0.22 },
});

afterEach(() => vi.restoreAllMocks());

describe("LeaderboardPage", () => {
  it("shows each planner, recovery, ablations and a trend", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          latest: {
            subset: "full",
            provider: "reference",
            seconds: 10,
            planners: { rule_based: planner(1, 0, 0.48), novel: planner(null, 1, null) },
            ablations: { no_reflection: { "known+faults success": 0.21 } },
          },
          history: [
            { date: "a", commit: "x", subset: "full", planners: { rule_based: { known: 1, novel: 0, faults: 0.4 } } },
            { date: "b", commit: "y", subset: "full", planners: { rule_based: { known: 1, novel: 0, faults: 0.48 } } },
          ],
        }),
        { status: 200 },
      ),
    );
    render(<LeaderboardPage />);
    const table = await screen.findByRole("table", { name: "Planner results" });
    expect(table).toHaveTextContent("rule based");
    expect(table).toHaveTextContent("48%");
    expect(table).toHaveTextContent("not run");
    expect(screen.getByRole("img", { name: "trend over 2 runs" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Recovery by fault" })).toHaveTextContent("22%");
    expect(screen.getByRole("list", { name: "Ablations" })).toHaveTextContent("no reflection: known+faults success 21%");
  });

  it("says when there are no results yet", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ latest: null, history: [] }), { status: 200 }));
    render(<LeaderboardPage />);
    expect(await screen.findByText(/No results yet/)).toBeInTheDocument();
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PlannerPicker } from "./PlannerPicker";
import { PLANNER_OPTIONS } from "./plannerOptions";

describe("PlannerPicker", () => {
  it("offers the four planners with friendly names", () => {
    render(<PlannerPicker value="rule_based" onChange={() => undefined} />);
    expect(PLANNER_OPTIONS.map((o) => o.value)).toEqual(["rule_based", "react", "behavior_tree", "htn"]);
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Steady",
      "Thinker",
      "Branching",
      "Step-by-step",
    ]);
  });

  it("reports the choice using the backend's planner name", () => {
    const onChange = vi.fn();
    render(<PlannerPicker value="rule_based" onChange={onChange} />);
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "htn" } });
    expect(onChange).toHaveBeenCalledWith("htn");
  });

  it("can be disabled while a job is being sent", () => {
    render(<PlannerPicker value="react" onChange={() => undefined} disabled />);
    expect(screen.getByRole("combobox")).toBeDisabled();
  });
});

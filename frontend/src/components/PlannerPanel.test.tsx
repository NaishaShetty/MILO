// PlannerPanel.test.tsx
//
// Purpose
// -------
// Verifies the Phase 4 planner UI flow: choosing a strategy, generating
// a plan, seeing its steps and validation status, and comparing
// strategies -- mocking `api/planner.ts` entirely so no test here makes
// a real network request, mirroring `App.test.tsx`'s own convention
// for the Language flow.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SingleTask } from "../api/types";
import { PlannerPanel } from "./PlannerPanel";

vi.mock("../api/planner", async () => {
  const actual = await vi.importActual<typeof import("../api/planner")>("../api/planner");
  return {
    ...actual,
    planTask: vi.fn(),
    evaluatePlanners: vi.fn(),
  };
});

import { evaluatePlanners, planTask } from "../api/planner";

const mockedPlanTask = vi.mocked(planTask);
const mockedEvaluatePlanners = vi.mocked(evaluatePlanners);

const TASK: SingleTask = {
  task_type: "single",
  task_id: "t1",
  goal: "store",
  object: "apple",
  target: "refrigerator",
  needs_clarification: false,
};

beforeEach(() => {
  mockedPlanTask.mockReset();
  mockedEvaluatePlanners.mockReset();
});

describe("PlannerPanel", () => {
  it("defaults to the rule_based strategy selected", () => {
    render(<PlannerPanel task={TASK} />);
    expect(screen.getByRole("radio", { name: "Rule Based" })).toBeChecked();
  });

  it("generates a plan and renders its steps and validation status", async () => {
    mockedPlanTask.mockResolvedValue({
      success: true,
      planner_type: "rule_based",
      latency_ms: 1.2,
      errors: [],
      plan: {
        plan_id: "p1",
        task_id: "t1",
        planner_type: "rule_based",
        goal_summary: {},
        status: "valid",
        created_at: 0,
        metadata: {},
        steps: [
          {
            step_id: 1,
            action: "locate",
            target: "apple",
            parameters: {},
            description: "Locate apple",
            preconditions: [],
            postconditions: [],
            status: "pending",
          },
        ],
      },
      validation: { valid: true, issues: [], goal_satisfied: true },
    });

    const user = userEvent.setup();
    render(<PlannerPanel task={TASK} />);
    await user.click(screen.getByRole("button", { name: /generate plan/i }));

    expect(await screen.findByText("Locate apple")).toBeInTheDocument();
    expect(screen.getByText("✓ Plan Valid")).toBeInTheDocument();
    expect(mockedPlanTask).toHaveBeenCalledWith(TASK, "rule_based");
  });

  it("shows the react_fallback note when ReAct falls back to rule-based", async () => {
    mockedPlanTask.mockResolvedValue({
      success: true,
      planner_type: "react",
      latency_ms: 1.2,
      errors: [],
      plan: {
        plan_id: "p1",
        task_id: "t1",
        planner_type: "react",
        goal_summary: {},
        status: "valid",
        created_at: 0,
        metadata: { react_fallback: true },
        steps: [],
      },
      validation: { valid: true, issues: [], goal_satisfied: null },
    });

    const user = userEvent.setup();
    render(<PlannerPanel task={TASK} />);
    await user.click(screen.getByRole("radio", { name: "ReAct" }));
    await user.click(screen.getByRole("button", { name: /generate plan/i }));

    expect(await screen.findByText(/fell back to Rule Based/i)).toBeInTheDocument();
  });

  it("shows an error message when planning fails outright", async () => {
    mockedPlanTask.mockResolvedValue({
      success: false,
      planner_type: "rule_based",
      latency_ms: 1.0,
      errors: ["Goal 'store' requires a 'target' but none was given."],
      plan: null,
      validation: null,
    });

    const user = userEvent.setup();
    render(<PlannerPanel task={TASK} />);
    await user.click(screen.getByRole("button", { name: /generate plan/i }));

    expect(await screen.findByText(/no plan could be generated/i)).toBeInTheDocument();
  });

  it("renders a planner comparison table", async () => {
    mockedEvaluatePlanners.mockResolvedValue({
      task_id: "t1",
      results: [
        {
          planner_type: "rule_based",
          success: true,
          valid: true,
          goal_satisfied: true,
          latency_ms: 4.2,
          step_count: 8,
          invalid_action_count: 0,
          redundant_step_count: 0,
        },
      ],
    });

    const user = userEvent.setup();
    render(<PlannerPanel task={TASK} />);
    await user.click(screen.getByRole("button", { name: /compare strategies/i }));

    await waitFor(() => expect(screen.getByRole("table")).toBeInTheDocument());
    expect(screen.getAllByText("Rule Based").length).toBeGreaterThan(0);
    expect(screen.getByText(/4\.20/)).toBeInTheDocument();
  });
});

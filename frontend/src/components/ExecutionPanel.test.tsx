// ExecutionPanel.test.tsx
//
// Purpose
// -------
// Verifies the Phase 5 execution UI flow: executing a valid plan,
// showing robot state/step list/log, surfacing a start failure, and
// cancelling a running execution -- mocking `api/execution.ts`
// entirely so no test here makes a real network request, mirroring
// `PlannerPanel.test.tsx`'s own convention.
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Plan } from "../api/plannerTypes";
import { ExecutionPanel } from "./ExecutionPanel";

vi.mock("../api/execution", async () => {
  const actual = await vi.importActual<typeof import("../api/execution")>("../api/execution");
  return {
    ...actual,
    startExecution: vi.fn(),
    getExecution: vi.fn(),
    cancelExecution: vi.fn(),
  };
});

import { cancelExecution, ExecutionApiError, getExecution, startExecution } from "../api/execution";

const mockedStart = vi.mocked(startExecution);
const mockedGet = vi.mocked(getExecution);
const mockedCancel = vi.mocked(cancelExecution);

const VALID_PLAN: Plan = {
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
      action: "pickup",
      target: "apple",
      parameters: {},
      description: "Pick up apple",
      preconditions: [],
      postconditions: [],
      status: "pending",
    },
  ],
};

beforeEach(() => {
  mockedStart.mockReset();
  mockedGet.mockReset();
  mockedCancel.mockReset();
});

describe("ExecutionPanel", () => {
  it("disables the Execute button for an invalid plan", () => {
    render(<ExecutionPanel plan={{ ...VALID_PLAN, status: "invalid" }} />);
    expect(screen.getByRole("button", { name: /execute plan/i })).toBeDisabled();
  });

  it("runs a plan that completes immediately and shows the result", async () => {
    mockedStart.mockResolvedValue({
      execution_id: "e1",
      plan_id: "p1",
      task_id: "t1",
      status: "success",
      step_results: [
        { step_id: 1, action: "pickup", target: "apple", status: "completed" },
      ],
      events: [
        {
          timestamp: 0,
          execution_id: "e1",
          plan_id: "p1",
          step_id: 1,
          action: "pickup",
          target: "apple",
          status: "success",
        },
      ],
    });

    const user = userEvent.setup();
    render(<ExecutionPanel plan={VALID_PLAN} />);
    await user.click(screen.getByRole("button", { name: /execute plan/i }));

    expect(await screen.findByText(/Robot state: SUCCESS/i)).toBeInTheDocument();
    expect(mockedStart).toHaveBeenCalledWith(VALID_PLAN);
  });

  it("shows an error message when starting execution fails", async () => {
    mockedStart.mockRejectedValue(
      new ExecutionApiError(503, "execution_unavailable", "No simulator is running."),
    );

    const user = userEvent.setup();
    render(<ExecutionPanel plan={VALID_PLAN} />);
    await user.click(screen.getByRole("button", { name: /execute plan/i }));

    expect(await screen.findByText(/no simulator is running/i)).toBeInTheDocument();
  });

  it("polls while running and lets the user cancel", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      mockedStart.mockResolvedValue({
        execution_id: "e1",
        plan_id: "p1",
        task_id: "t1",
        status: "running",
        step_results: [
          { step_id: 1, action: "pickup", target: "apple", status: "running" },
        ],
        events: [],
      });
      mockedGet.mockResolvedValue({
        execution_id: "e1",
        plan_id: "p1",
        task_id: "t1",
        status: "running",
        step_results: [
          { step_id: 1, action: "pickup", target: "apple", status: "running" },
        ],
        events: [],
      });
      mockedCancel.mockResolvedValue({
        execution_id: "e1",
        plan_id: "p1",
        task_id: "t1",
        status: "running",
        step_results: [],
        events: [],
      });

      render(<ExecutionPanel plan={VALID_PLAN} />);
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: /execute plan/i }));
      });

      expect(await screen.findByText(/Robot state: RUNNING/i)).toBeInTheDocument();
      const cancelButton = screen.getByRole("button", { name: /cancel/i });

      await act(async () => {
        fireEvent.click(cancelButton);
        await Promise.resolve();
      });

      await waitFor(() => expect(mockedCancel).toHaveBeenCalledWith("e1"));
    } finally {
      vi.useRealTimers();
    }
  });
});

// DecisionCard.test.tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DecisionCard } from "./DecisionCard";
import * as tasksApi from "../api/tasks";

vi.mock("../api/tasks", async () => ({ ...(await vi.importActual<object>("../api/tasks")), decide: vi.fn() }));

describe("DecisionCard", () => {
  it("asks about a risky step and sends approve or skip", async () => {
    vi.mocked(tasksApi.decide).mockResolvedValue({} as never);
    render(
      <DecisionCard
        taskId="t1"
        pending={{ kind: "step", why: "the toaster could be dangerous", text: "Turning on the toaster.", step_id: 3 }}
      />,
    );
    expect(screen.getByRole("alertdialog")).toHaveTextContent("I'm asking because the toaster could be dangerous.");
    fireEvent.click(screen.getByRole("button", { name: "Yes, go ahead" }));
    await waitFor(() => expect(tasksApi.decide).toHaveBeenCalledWith("t1", "approve", undefined));
    fireEvent.click(screen.getByRole("button", { name: "Skip that step" }));
    await waitFor(() => expect(tasksApi.decide).toHaveBeenCalledWith("t1", "skip", undefined));
  });

  it("previews a plan and sends only the steps left ticked", async () => {
    vi.mocked(tasksApi.decide).mockResolvedValue({} as never);
    const steps = [
      { step_id: 1, action: "open", target: "fridge", text: "Opening the fridge." },
      { step_id: 2, action: "look_around", target: null, text: "Looking around." },
    ];
    render(<DecisionCard taskId="t1" pending={{ kind: "plan", why: "I worked this plan out myself.", steps }} />);
    fireEvent.click(screen.getByLabelText(/Looking around/));
    fireEvent.click(screen.getByRole("button", { name: "Go ahead with 1 steps" }));
    await waitFor(() => expect(tasksApi.decide).toHaveBeenCalledWith("t1", "approve", [{ step_id: 1 }]));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(tasksApi.decide).toHaveBeenCalledWith("t1", "cancel", undefined));
  });
});

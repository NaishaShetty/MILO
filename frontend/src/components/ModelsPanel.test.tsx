import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import * as labApi from "../api/lab";
import { confidenceWord } from "../utils/friendly";
import { ModelsPanel } from "./ModelsPanel";

vi.mock("../api/lab", async () => ({ ...(await vi.importActual<object>("../api/lab")), getModels: vi.fn(), setOutcomeMode: vi.fn() }));

const model = (mode: "off" | "shadow" | "on") => ({
  name: "outcome_predictor", title: "Step outcome predictor", available: true, version: "v1", mode,
  metrics: { auroc: 0.968, pr_auc: 0.99, brier: 0.04, ece: 0.005 }, trained_on: 19430, date: "2026-11-24",
  shadow: { compared: 10, agree: 6, used: 0, fallbacks: 0 }, latency: { p50_ms: 5, p95_ms: 7 },
  drift_score: 0.5, healthy: true, problem: null, explains: "Off: built-in rules.",
});

describe("ModelsPanel", () => {
  it("shows version, metrics, shadow comparison and switches the mode", async () => {
    vi.mocked(labApi.getModels).mockResolvedValue({ models: [model("off")] });
    vi.mocked(labApi.setOutcomeMode).mockResolvedValue({ models: [model("shadow")] });
    render(<ModelsPanel />);
    expect(await screen.findByText("version v1")).toBeInTheDocument();
    expect(screen.getByText(/AUROC 0.968/)).toBeInTheDocument();
    expect(screen.getByText(/agreed with the built-in rules on 6 of 10/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Shadow" }));
    await waitFor(() => expect(labApi.setOutcomeMode).toHaveBeenCalledWith("shadow"));
    await waitFor(() => expect(screen.getByRole("button", { name: "Shadow" })).toHaveAttribute("aria-pressed", "true"));
  });

  it("lists the other models read-only with their on/off state and headline number", async () => {
    vi.mocked(labApi.getModels).mockResolvedValue({
      models: [
        model("off"),
        { name: "instruction_parser", title: "Instruction parser", available: true, enabled: false,
          headline: "Understands new wordings: 0.62 exact vs 0.14", explains: "Tried before the phrasebook." },
      ],
    });
    render(<ModelsPanel />);
    expect(await screen.findByText("Instruction parser")).toBeInTheDocument();
    expect(screen.getByText(/0.62 exact vs 0.14/)).toBeInTheDocument();
    expect(screen.getByText("off", { selector: ".pill" })).toBeInTheDocument();
    expect(screen.getByText(/Input drift: 0.50/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Shadow" })).toHaveLength(1);
  });

  it("says what went wrong when the list can't load", async () => {
    vi.mocked(labApi.getModels).mockRejectedValue(new Error("down"));
    render(<ModelsPanel />);
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't load");
  });
});

describe("confidenceWord", () => {
  it("uses plain language", () => {
    expect(confidenceWord(0.95)).toBe("Pretty sure");
    expect(confidenceWord(0.7)).toBe("Fairly sure");
    expect(confidenceWord(0.4)).toBe("Not sure");
    expect(confidenceWord(0.1)).toBe("Probably won't work");
  });
});

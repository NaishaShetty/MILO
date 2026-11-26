// MemoryPage.test.tsx -- trust labels, quarantine review, pin / fix / delete.
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MemoryPage } from "./MemoryPage";
import * as memoryApi from "../api/memory";
import * as hook from "../hooks/useMemoryList";

vi.mock("../api/memory", async () => ({
  ...(await vi.importActual<object>("../api/memory")),
  editMemory: vi.fn(),
  deleteMemory: vi.fn(),
  forgetMemory: vi.fn(),
}));
vi.mock("../hooks/useMemoryList", () => ({ useMemoryList: vi.fn() }));

const fact = (id: string, place: string, provenance: string, status = "active") => ({
  memory_id: id,
  memory_type: "user",
  content: `apple goes ${place}`,
  provenance,
  status,
  confidence: 1,
  created_at: Date.now() / 1000,
  updated_at: Date.now() / 1000,
  metadata: { subject: "apple", predicate: "stored_in", object: place },
});

function setup() {
  const refresh = vi.fn();
  vi.mocked(hook.useMemoryList).mockReturnValue({
    memories: [fact("good", "fridge", "user_input"), fact("bad", "sofa", "imported", "quarantined")] as never,
    countsByType: {},
    status: "success",
    error: null,
    refresh,
    quarantined: 1,
    trust: {
      good: { source: "user", trust: 3, effective_confidence: 1, pinned: false, quarantined: false, contradicted: 0 },
      bad: {
        source: "imported",
        trust: 0,
        effective_confidence: 1,
        pinned: false,
        quarantined: true,
        quarantine_reason: "it contradicts what I know from a user (apple stored_in fridge)",
        contradicted: 0,
        claimed_source: "user",
      },
    },
  });
  vi.mocked(memoryApi.editMemory).mockResolvedValue({} as never);
  vi.mocked(memoryApi.deleteMemory).mockResolvedValue();
  return refresh;
}

describe("MemoryPage trust", () => {
  it("shows where each memory came from and why one is set aside", () => {
    setup();
    render(<MemoryPage />);
    expect(screen.getByText("you told me")).toBeInTheDocument();
    expect(screen.getByText("imported")).toBeInTheDocument();
    // an import that says it came from the user is labelled as a claim, not believed
    expect(screen.getByText("claims “you told me”")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("I've set aside 1 memory");
    expect(screen.getByRole("note")).toHaveTextContent("it contradicts what I know from a user");
  });

  it("pins, fixes the place, releases and deletes", async () => {
    const refresh = setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<MemoryPage />);
    fireEvent.click(screen.getAllByRole("button", { name: "Pin" })[0]);
    await waitFor(() => expect(memoryApi.editMemory).toHaveBeenCalledWith("good", { pinned: true }));
    fireEvent.click(screen.getAllByRole("button", { name: "Fix the place" })[0]);
    fireEvent.change(screen.getByLabelText("Correct place"), { target: { value: "drawer" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(memoryApi.editMemory).toHaveBeenCalledWith("good", { place: "drawer" }));
    fireEvent.click(screen.getByRole("button", { name: "Use it again" }));
    await waitFor(() => expect(memoryApi.editMemory).toHaveBeenCalledWith("bad", { quarantined: false }));
    fireEvent.click(screen.getAllByRole("button", { name: "Delete" })[1]);
    await waitFor(() => expect(memoryApi.deleteMemory).toHaveBeenCalledWith("bad"));
    expect(refresh).toHaveBeenCalled();
  });
});

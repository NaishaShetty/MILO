// VisionPanel.test.tsx
//
// Purpose
// -------
// End-to-end (within the frontend) test of the Vision panel's user
// flow: entering a detection prompt, submitting it, seeing a loading
// state, and seeing each outcome (populated scene, empty scene, API
// error, network failure) -- mirrors `App.test.tsx`'s structure and
// mocking discipline (mocks `src/api/vision.ts` entirely, no real
// network request in this file).
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { VisionPanel } from "./VisionPanel";
import { VisionApiError, perceive } from "../api/vision";
import type { PerceiveResponse } from "../api/visionTypes";

vi.mock("../api/vision", async () => {
  const actual = await vi.importActual<typeof import("../api/vision")>("../api/vision");
  return {
    ...actual,
    perceive: vi.fn(),
  };
});

const mockedPerceive = vi.mocked(perceive);

beforeEach(() => {
  mockedPerceive.mockReset();
});

async function submitPrompt(): Promise<void> {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /perceive/i }));
}

const BASE_RESPONSE: PerceiveResponse = {
  objects: [],
  status: { object_count: 0, tracked_count: 0, depth_available_count: 0, depth_source: null },
  scene_changes: [],
  camera_image_png_b64: "img-data",
  depth_image_png_b64: null,
  depth_legend: null,
};

describe("VisionPanel", () => {
  it("renders the prompt input with a default value and an enabled submit button", () => {
    render(<VisionPanel />);

    expect(screen.getByLabelText(/detection prompt/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /perceive/i })).toBeEnabled();
  });

  it("shows a loading state while the request is in flight", async () => {
    let resolveRequest: (value: PerceiveResponse) => void = () => {};
    mockedPerceive.mockReturnValue(
      new Promise((resolve) => {
        resolveRequest = resolve;
      }),
    );

    render(<VisionPanel />);
    await submitPrompt();

    expect(screen.getByText(/perceiving current scene/i)).toBeInTheDocument();

    resolveRequest(BASE_RESPONSE);
    await waitFor(() =>
      expect(screen.queryByText(/perceiving current scene/i)).not.toBeInTheDocument(),
    );
  });

  it("renders the camera image and perception status on success", async () => {
    mockedPerceive.mockResolvedValue({
      ...BASE_RESPONSE,
      objects: [
        {
          object_id: 3,
          label: "mug",
          confidence: 0.94,
          bbox: [1, 2, 3, 4],
          depth: 1.84,
          depth_source: "ground_truth",
          position_3d: [0.1, 0.2, 1.84],
          track_status: "tracked",
          frames_observed: 5,
          first_seen: 1,
          last_seen: 5,
        },
      ],
      status: { object_count: 1, tracked_count: 1, depth_available_count: 1, depth_source: "ground_truth" },
    });

    render(<VisionPanel />);
    await submitPrompt();

    const image = await screen.findByAltText(/annotated camera view/i);
    expect(image).toHaveAttribute("src", "data:image/png;base64,img-data");

    // Both "Objects" and "Tracked" rows read "1" for this fixture.
    expect(screen.getAllByText("1")).toHaveLength(2);
    const inspector = screen.getByText("Object Inspector").closest(".object-inspector");
    expect(inspector).not.toBeNull();
    expect(within(inspector as HTMLElement).getByText("mug")).toBeInTheDocument();
    expect(within(inspector as HTMLElement).getByText("#3")).toBeInTheDocument();
    expect(within(inspector as HTMLElement).getByText("TRACKED")).toBeInTheDocument();
  });

  it("shows the object inspector's empty state when no objects are perceived", async () => {
    mockedPerceive.mockResolvedValue(BASE_RESPONSE);

    render(<VisionPanel />);
    await submitPrompt();

    expect(await screen.findByText(/no objects perceived yet/i)).toBeInTheDocument();
  });

  it("renders multiple objects in the inspector table", async () => {
    mockedPerceive.mockResolvedValue({
      ...BASE_RESPONSE,
      objects: [
        {
          object_id: 1,
          label: "apple",
          confidence: 0.9,
          bbox: [0, 0, 1, 1],
          depth: null,
          depth_source: null,
          position_3d: null,
          track_status: "new",
          frames_observed: 1,
          first_seen: 1,
          last_seen: 1,
        },
        {
          object_id: 2,
          label: "bottle",
          confidence: 0.8,
          bbox: [0, 0, 1, 1],
          depth: null,
          depth_source: null,
          position_3d: null,
          track_status: "new",
          frames_observed: 1,
          first_seen: 1,
          last_seen: 1,
        },
      ],
      status: { object_count: 2, tracked_count: 2, depth_available_count: 0, depth_source: null },
    });

    render(<VisionPanel />);
    await submitPrompt();

    expect(await screen.findByText("apple")).toBeInTheDocument();
    expect(screen.getByText("bottle")).toBeInTheDocument();
  });

  it("renders scene changes when present", async () => {
    mockedPerceive.mockResolvedValue({
      ...BASE_RESPONSE,
      scene_changes: [
        { change_type: "reappeared", tracking_id: 7, label: "bottle", detail: "Reappeared." },
      ],
    });

    render(<VisionPanel />);
    await submitPrompt();

    expect(await screen.findByText(/bottle #7/)).toBeInTheDocument();
    expect(screen.getByText("Reappeared.")).toBeInTheDocument();
  });

  it("renders a safe error message for a vision-unavailable failure", async () => {
    mockedPerceive.mockRejectedValue(
      new VisionApiError(503, {
        category: "vision_unavailable",
        message: "The vision system is not available on this server.",
      }),
    );

    render(<VisionPanel />);
    await submitPrompt();

    expect(await screen.findByText("Vision System Unavailable")).toBeInTheDocument();
    expect(
      screen.getByText("The vision system is not available on this server."),
    ).toBeInTheDocument();
  });

  it("renders a network-failure message when the backend cannot be reached", async () => {
    mockedPerceive.mockRejectedValue(new TypeError("Failed to fetch"));

    render(<VisionPanel />);
    await submitPrompt();

    expect(await screen.findByText("Cannot Reach Vision Service")).toBeInTheDocument();
  });

  it("shows the camera panel's empty state before any perceive call", () => {
    render(<VisionPanel />);

    expect(screen.getByText(/no camera frame yet/i)).toBeInTheDocument();
  });
});

// vision.test.ts
//
// Purpose
// -------
// Unit tests for the Vision API client (`perceive`) -- mirrors
// `language.test.ts`'s structure exactly (mocks global `fetch`,
// verifies request shape, success resolution, and error mapping).
import { afterEach, describe, expect, it, vi } from "vitest";

import { VisionApiError, perceive } from "./vision";

function mockFetchOnce(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const SUCCESS_BODY = {
  objects: [],
  status: { object_count: 0, tracked_count: 0, depth_available_count: 0, depth_source: null },
  scene_changes: [],
  camera_image_png_b64: "abc123",
  depth_image_png_b64: null,
  depth_legend: null,
};

describe("perceive", () => {
  it("POSTs to the versioned vision endpoint with the prompt as JSON", async () => {
    mockFetchOnce(200, SUCCESS_BODY);

    await perceive("mug. apple.");

    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/vision/perceive",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: "mug. apple." }),
      }),
    );
  });

  it("resolves with the parsed response body on success", async () => {
    mockFetchOnce(200, SUCCESS_BODY);

    await expect(perceive("mug.")).resolves.toEqual(SUCCESS_BODY);
  });

  it("throws VisionApiError with the backend's category/message on failure", async () => {
    mockFetchOnce(503, {
      category: "vision_unavailable",
      message: "The vision system is not available on this server.",
    });

    await expect(perceive("mug.")).rejects.toMatchObject({
      category: "vision_unavailable",
      status: 503,
      message: "The vision system is not available on this server.",
    });
  });

  it("throws VisionApiError instances specifically", async () => {
    mockFetchOnce(422, { category: "invalid_request", message: "bad request" });

    await expect(perceive("mug.")).rejects.toBeInstanceOf(VisionApiError);
  });

  it("falls back to a generic message when the error body is malformed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        json: async () => {
          throw new SyntaxError("not json");
        },
      }),
    );

    await expect(perceive("mug.")).rejects.toMatchObject({
      category: "internal_error",
    });
  });
});

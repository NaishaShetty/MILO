// language.test.ts
//
// Purpose
// -------
// Unit tests for the centralized API client itself (`parseInstruction`)
// -- separate from `App.test.tsx`, which mocks this module entirely.
// These tests mock the global `fetch` instead, verifying this file's
// own responsibilities: building the right request, parsing a
// successful response, and translating a non-2xx response into a
// `LanguageApiError` with the backend's safe `category`/`message`
// preserved.
import { afterEach, describe, expect, it, vi } from "vitest";

import { getLanguageStatus, LanguageApiError, parseInstruction } from "./language";

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

describe("parseInstruction", () => {
  it("POSTs to the versioned language endpoint with the instruction as JSON", async () => {
    mockFetchOnce(200, {
      status: "ok",
      result: { task_type: "single", task_id: "t1", needs_clarification: false },
    });

    await parseInstruction("Bring me the red mug.");

    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/language/parse",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction: "Bring me the red mug." }),
      }),
    );
  });

  it("resolves with the parsed response body on success", async () => {
    const body = {
      status: "ok",
      result: { task_type: "single", task_id: "t1", needs_clarification: false },
    };
    mockFetchOnce(200, body);

    await expect(parseInstruction("x")).resolves.toEqual(body);
  });

  it("throws LanguageApiError with the backend's category/message on failure", async () => {
    mockFetchOnce(503, {
      category: "provider_unavailable",
      message: "The language service is temporarily unavailable. Please try again.",
    });

    await expect(parseInstruction("x")).rejects.toMatchObject({
      category: "provider_unavailable",
      status: 503,
      message: "The language service is temporarily unavailable. Please try again.",
    });
  });

  it("throws LanguageApiError instances specifically", async () => {
    mockFetchOnce(422, { category: "invalid_request", message: "bad request" });

    await expect(parseInstruction("x")).rejects.toBeInstanceOf(LanguageApiError);
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

    await expect(parseInstruction("x")).rejects.toMatchObject({
      category: "internal_error",
    });
  });
});

describe("getLanguageStatus", () => {
  it("GETs the language status endpoint and resolves with the body", async () => {
    const body = { provider: "openai", model: "gpt-4o-mini", configured: true, available: true };
    mockFetchOnce(200, body);

    await expect(getLanguageStatus()).resolves.toEqual(body);
    expect(fetch).toHaveBeenCalledWith("/api/v1/language");
  });

  it("throws on a non-2xx response", async () => {
    mockFetchOnce(500, { category: "internal_error", message: "boom" });
    await expect(getLanguageStatus()).rejects.toThrow();
  });
});

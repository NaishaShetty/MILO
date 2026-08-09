// client.test.ts
//
// Purpose
// -------
// Unit tests for the shared `request()`/`requestForm()` helpers --
// mirrors `execution.test.ts`'s convention of mocking the global
// `fetch` rather than a real backend.
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, request, requestForm } from "./client";

function mockFetchOnce(status: number, body: unknown, ok = status >= 200 && status < 300): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok,
      status,
      json: async () => body,
      text: async () => JSON.stringify(body),
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("request", () => {
  it("returns the parsed JSON body on success", async () => {
    mockFetchOnce(200, { hello: "world" });
    await expect(request("/api/v1/whatever")).resolves.toEqual({ hello: "world" });
  });

  it("sends a JSON Content-Type header by default", async () => {
    mockFetchOnce(200, {});
    await request("/api/v1/whatever");
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/whatever",
      expect.objectContaining({ headers: { "Content-Type": "application/json" } }),
    );
  });

  it("throws ApiError with the backend's category/message on failure", async () => {
    mockFetchOnce(404, { category: "task_not_found", message: "No task with id 'x'." });
    await expect(request("/api/v1/tasks/x")).rejects.toMatchObject({
      status: 404,
      category: "task_not_found",
      message: "No task with id 'x'.",
    });
  });

  it("throws ApiError with a generic message when the error body isn't JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => {
          throw new Error("not json");
        },
      }),
    );
    await expect(request("/api/v1/whatever")).rejects.toBeInstanceOf(ApiError);
    await expect(request("/api/v1/whatever")).rejects.toMatchObject({ category: "internal_error" });
  });
});

describe("requestForm", () => {
  it("POSTs the given FormData without setting a Content-Type header", async () => {
    mockFetchOnce(200, { text: "hello" });
    const form = new FormData();
    form.append("file", new Blob(["audio"]), "clip.webm");

    await requestForm("/api/v1/speech/transcribe", form);

    const call = vi.mocked(fetch).mock.calls[0];
    expect(call[0]).toBe("/api/v1/speech/transcribe");
    expect((call[1] as RequestInit).method).toBe("POST");
    expect((call[1] as RequestInit).body).toBe(form);
    expect((call[1] as RequestInit).headers).toBeUndefined();
  });

  it("throws ApiError on a non-2xx response", async () => {
    mockFetchOnce(422, { category: "empty_audio", message: "No speech detected." });
    await expect(requestForm("/api/v1/speech/transcribe", new FormData())).rejects.toMatchObject({
      status: 422,
      category: "empty_audio",
    });
  });
});

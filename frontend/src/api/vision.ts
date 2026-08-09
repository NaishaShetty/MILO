// vision.ts
//
// Purpose
// -------
// The *only* place in this frontend that issues an HTTP request to the
// backend's Vision API. Mirrors `language.ts`'s pattern exactly
// (relative URL, typed error class, `safeReadErrorBody` fallback) --
// see that file's docstring for the full rationale, in particular why
// this always calls a relative `/api/v1/vision/...` path and never
// touches a model, the simulator, or a credential directly: all of that
// stays server-side (see `backend/api/models/vision.py`'s module
// docstring on the API/frontend boundary).

import type { PerceiveResponse, VisionApiErrorBody } from "./visionTypes";

/**
 * Thrown by `perceive()` for any non-2xx response. Carries the
 * backend's own safe `category`/`message` -- see
 * `backend/api/routes/vision.py`'s docstring on why a 503
 * ("vision_unavailable") is a normal, expected outcome (no simulator
 * connected on this server), not a bug.
 */
export class VisionApiError extends Error {
  readonly category: VisionApiErrorBody["category"];
  readonly status: number;

  constructor(status: number, body: VisionApiErrorBody) {
    super(body.message);
    this.name = "VisionApiError";
    this.status = status;
    this.category = body.category;
  }
}

const DEFAULT_ERROR_MESSAGE = "The vision service could not be reached. Please try again.";

/**
 * Submits one detection prompt to `POST /api/v1/vision/perceive` and
 * returns the resulting `PerceiveResponse` (spatial objects, scene
 * changes, and server-rendered camera/depth images). Throws
 * `VisionApiError` for any non-2xx response; lets a network-level
 * failure (`fetch` rejecting) propagate as-is, same distinction
 * `parseInstruction` makes -- see `language.ts`.
 */
export async function perceive(prompt: string): Promise<PerceiveResponse> {
  const response = await fetch("/api/v1/vision/perceive", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt }),
  });

  if (!response.ok) {
    const body = await safeReadErrorBody(response);
    throw new VisionApiError(response.status, body);
  }

  return (await response.json()) as PerceiveResponse;
}

/**
 * Reads the backend's `{category, message}` error body, falling back to
 * a generic message if the response body is missing or malformed. See
 * `language.ts`'s `safeReadErrorBody` -- identical rationale.
 */
async function safeReadErrorBody(response: Response): Promise<VisionApiErrorBody> {
  try {
    const parsed = (await response.json()) as Partial<VisionApiErrorBody>;
    if (typeof parsed.message === "string" && typeof parsed.category === "string") {
      return { category: parsed.category, message: parsed.message };
    }
  } catch {
    // Response body was not JSON -- fall through to the generic message.
  }
  return { category: "internal_error", message: DEFAULT_ERROR_MESSAGE };
}

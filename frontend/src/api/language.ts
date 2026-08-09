// language.ts
//
// Purpose
// -------
// The *only* place in this frontend that issues an HTTP request to
// the backend's Language API. Every UI component calls
// `parseInstruction()` from here instead of constructing its own
// `fetch()` call -- this is Phase 3.7's "centralized API client"
// requirement, and it is also what keeps the UI ignorant of Gemini,
// OpenAI, prompts, or retries: this file knows only the HTTP contract
// documented in `backend/docs/language_interface_spec.md` section 30,
// nothing about how the backend produces a `ParsedInstruction`.
//
// Why a relative URL, never an absolute one with a provider endpoint
// ---------------------------------------------------------------------
// This file calls `/api/v1/language/parse` -- never
// `generativelanguage.googleapis.com` or `api.openai.com`, and never
// reads an LLM API key from `import.meta.env` or anywhere else. The
// backend is the only component that ever holds an LLM credential
// (see `backend/language/config.py`'s Security note); a frontend that
// could reach an LLM provider directly would defeat that boundary
// entirely. In development, Vite's dev server proxies `/api` to the
// backend (see `vite.config.ts`); in production, the same relative
// path is expected to be served behind a reverse proxy in front of
// both the built frontend and the FastAPI process.

import type { ApiErrorBody, HealthResponse, ParseResponse } from "./types";

/**
 * Thrown by `parseInstruction()` for any non-2xx response. Carries the
 * backend's own safe `category`/`message` (never a raw stack trace or
 * credential -- the backend guarantees that, see
 * `backend/api/routes/language.py`'s "Error mapping" docstring
 * section) so a UI component can branch on `category` without
 * re-parsing response text.
 */
export class LanguageApiError extends Error {
  readonly category: ApiErrorBody["category"];
  readonly status: number;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "LanguageApiError";
    this.status = status;
    this.category = body.category;
  }
}

const DEFAULT_ERROR_MESSAGE =
  "The language service could not be reached. Please try again.";

/**
 * Submits one natural language instruction to
 * `POST /api/v1/language/parse` and returns the validated
 * `ParseResponse`. Throws `LanguageApiError` for any non-2xx response
 * (validation failure, clarification is NOT an error -- see
 * `ParseResponse.status` -- provider/timeout/internal failure) and
 * lets a network-level failure (`fetch` rejecting, e.g. the backend is
 * unreachable) propagate as-is so callers can distinguish "the server
 * answered with an error" from "there was no server to answer".
 */
export async function parseInstruction(instruction: string): Promise<ParseResponse> {
  const response = await fetch("/api/v1/language/parse", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ instruction }),
  });

  if (!response.ok) {
    const body = await safeReadErrorBody(response);
    throw new LanguageApiError(response.status, body);
  }

  return (await response.json()) as ParseResponse;
}

/**
 * Reads the backend's `{category, message}` error body, falling back
 * to a generic message if the response body is missing or malformed
 * -- e.g. an error surfaced by an intermediary (a reverse proxy, the
 * Vite dev server) rather than by the FastAPI app itself, which would
 * not match `ApiErrorBody`'s shape.
 */
async function safeReadErrorBody(response: Response): Promise<ApiErrorBody> {
  try {
    const parsed = (await response.json()) as Partial<ApiErrorBody>;
    if (typeof parsed.message === "string" && typeof parsed.category === "string") {
      return { category: parsed.category, message: parsed.message };
    }
  } catch {
    // Response body was not JSON -- fall through to the generic message.
  }
  return { category: "internal_error", message: DEFAULT_ERROR_MESSAGE };
}

/**
 * Checks `GET /health`. Used only by an optional dev-time status
 * indicator, never on the hot path of submitting an instruction --
 * see `backend/api/routes/health.py`'s docstring for why this
 * endpoint is intentionally cheap and provider-call-free.
 */
export async function checkHealth(): Promise<HealthResponse> {
  const response = await fetch("/health");
  if (!response.ok) {
    throw new Error("Health check failed.");
  }
  return (await response.json()) as HealthResponse;
}

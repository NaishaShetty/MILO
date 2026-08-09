// client.ts
//
// Purpose
// -------
// Shared HTTP helper for the newer Task/Agents/Speech API modules
// (`tasks.ts`, `agents.ts`, `speech.ts`). The existing per-domain
// modules (`language.ts`, `vision.ts`, `planner.ts`, `execution.ts`)
// each hand-roll an identical `{category, message}` error-parsing
// `fetch()` wrapper -- this file is that same pattern, extracted once,
// so the three new modules don't repeat it a fourth/fifth/sixth time.
// Same rules as every existing module: relative URLs only (never an
// absolute URL, never a credential), so the same built bundle works
// behind any reverse proxy -- see `vite.config.ts`'s dev-proxy
// docstring and `language.ts`'s module docstring.

/** Backend error body shape, shared by every route in this API. */
export interface ApiErrorBody {
  category: string;
  message: string;
}

const DEFAULT_ERROR_MESSAGE = "The backend could not be reached. Please try again.";

/** Thrown by `request()`/`requestForm()` for any non-2xx response. */
export class ApiError extends Error {
  readonly category: string;
  readonly status: number;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.category = body.category;
  }
}

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
 * Issues a JSON request (GET by default, or whatever `init.method` says)
 * and parses the JSON response. Network-level failures (`fetch`
 * rejecting -- backend unreachable) propagate as-is, same distinction
 * every existing API module makes, so callers can tell "server
 * answered with an error" apart from "no server to answer."
 */
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!response.ok) {
    throw new ApiError(response.status, await safeReadErrorBody(response));
  }

  // A 204/empty body (not currently used by this API, but kept safe)
  // has nothing to parse.
  const text = await response.text();
  return (text.length > 0 ? JSON.parse(text) : undefined) as T;
}

/**
 * Issues a `multipart/form-data` request -- used only by
 * `speech.ts::transcribe()`, whose backend route takes an `UploadFile`,
 * not a JSON body. Deliberately does not set a `Content-Type` header:
 * the browser must set it itself (including the multipart boundary),
 * which it only does when `fetch` is not given one explicitly.
 */
export async function requestForm<T>(path: string, form: FormData): Promise<T> {
  const response = await fetch(path, { method: "POST", body: form });

  if (!response.ok) {
    throw new ApiError(response.status, await safeReadErrorBody(response));
  }

  const text = await response.text();
  return (text.length > 0 ? JSON.parse(text) : undefined) as T;
}

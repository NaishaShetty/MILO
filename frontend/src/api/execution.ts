// execution.ts
//
// Purpose
// -------
// The *only* place in this frontend that issues an HTTP request to the
// backend's Phase 5 Execution API (`backend/api/routes/execution.py`) --
// mirrors `planner.ts`'s "centralized API client" convention exactly.
// Every UI component calls `startExecution()`/`getExecution()`/
// `cancelExecution()` from here instead of constructing its own
// `fetch()` call.
//
// Same relative-URL, no-credential rule as `planner.ts`/`language.ts`:
// this file calls `/api/v1/execution/...`, never an absolute URL.

import type { Plan } from "./plannerTypes";
import type { ExecutionEvent, ExecutionRecord, StepExecutionRecord } from "./executionTypes";

const DEFAULT_ERROR_MESSAGE = "The execution service could not be reached. Please try again.";

/** Thrown by this module's functions for any non-2xx response. */
export class ExecutionApiError extends Error {
  readonly category: string;
  readonly status: number;

  constructor(status: number, category: string, message: string) {
    super(message);
    this.name = "ExecutionApiError";
    this.status = status;
    this.category = category;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });

  if (!response.ok) {
    let category = "internal_error";
    let message = DEFAULT_ERROR_MESSAGE;
    try {
      const parsed = (await response.json()) as Partial<{ category: string; message: string }>;
      if (typeof parsed.message === "string") message = parsed.message;
      if (typeof parsed.category === "string") category = parsed.category;
    } catch {
      // Response body was not JSON -- fall through to the generic message.
    }
    throw new ExecutionApiError(response.status, category, message);
  }

  return (await response.json()) as T;
}

/**
 * Submits `plan` to `POST /api/v1/execution/start`. Returns
 * immediately (202) with the initial ExecutionRecord -- the plan runs
 * on the backend in the background; poll `getExecution()` for
 * progress. Throws `ExecutionApiError` for 503 (no simulator), 409
 * (another execution already running), or 422 (plan not executable).
 */
export async function startExecution(
  plan: Plan,
  options?: { maxStepRetries?: number; stepTimeoutS?: number },
): Promise<ExecutionRecord> {
  return request<ExecutionRecord>("/api/v1/execution/start", {
    method: "POST",
    body: JSON.stringify({
      plan,
      max_step_retries: options?.maxStepRetries ?? 0,
      step_timeout_s: options?.stepTimeoutS ?? null,
    }),
  });
}

/** Fetches the current ExecutionRecord for `executionId`. */
export async function getExecution(executionId: string): Promise<ExecutionRecord> {
  return request<ExecutionRecord>(`/api/v1/execution/${encodeURIComponent(executionId)}`);
}

/** Requests cancellation; takes effect at the next step boundary. */
export async function cancelExecution(executionId: string): Promise<ExecutionRecord> {
  return request<ExecutionRecord>(
    `/api/v1/execution/${encodeURIComponent(executionId)}/cancel`,
    { method: "POST" },
  );
}

export async function getExecutionSteps(executionId: string): Promise<StepExecutionRecord[]> {
  return request<StepExecutionRecord[]>(
    `/api/v1/execution/${encodeURIComponent(executionId)}/steps`,
  );
}

export async function getExecutionEvents(executionId: string): Promise<ExecutionEvent[]> {
  return request<ExecutionEvent[]>(
    `/api/v1/execution/${encodeURIComponent(executionId)}/events`,
  );
}

// planner.ts
//
// Purpose
// -------
// The *only* place in this frontend that issues an HTTP request to the
// backend's Planning API (`backend/api/routes/planner.py`) -- mirrors
// `language.ts`'s "centralized API client" convention exactly. Every
// UI component calls `planTask()`/`evaluatePlanners()` from here
// instead of constructing its own `fetch()` call.
//
// Same relative-URL, no-credential rule as `language.ts`: this file
// calls `/api/v1/planner/...`, never an absolute URL, and never reads
// or forwards an LLM API key -- the backend is the only component
// that ever holds one (`backend/language/config.py`'s Security note
// applies here too, since `react` planning ultimately calls an LLM
// server-side).

import type { SingleTask } from "./types";
import type { EvaluateResponse, PlannerType, PlanningResult } from "./plannerTypes";

const DEFAULT_ERROR_MESSAGE = "The planning service could not be reached. Please try again.";

/** Thrown by this module's functions for any non-2xx response. */
export class PlannerApiError extends Error {
  readonly category: string;
  readonly status: number;

  constructor(status: number, category: string, message: string) {
    super(message);
    this.name = "PlannerApiError";
    this.status = status;
    this.category = category;
  }
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
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
    throw new PlannerApiError(response.status, category, message);
  }

  return (await response.json()) as T;
}

/**
 * Submits one task to `POST /api/v1/planner/plan` and returns the
 * `PlanningResult` -- always a 200 with `success`/`validation` fields
 * to check, except for a request-shape problem (unrecognized
 * `planner_type`), which throws `PlannerApiError`.
 */
export async function planTask(
  task: SingleTask,
  plannerType: PlannerType = "rule_based",
): Promise<PlanningResult> {
  return postJson<PlanningResult>("/api/v1/planner/plan", {
    task,
    planner_type: plannerType,
  });
}

/**
 * Submits one task to `POST /api/v1/planner/evaluate` and returns
 * measured metrics for every requested (default: all) planning
 * strategy -- used by the planner-comparison dashboard.
 */
export async function evaluatePlanners(
  task: SingleTask,
  plannerTypes?: PlannerType[],
): Promise<EvaluateResponse> {
  return postJson<EvaluateResponse>("/api/v1/planner/evaluate", {
    task,
    planner_types: plannerTypes,
  });
}

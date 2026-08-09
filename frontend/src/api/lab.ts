// lab.ts
//
// Purpose
// -------
// The *only* place in this frontend that issues an HTTP request to the
// Phase 8.2 MILO Lab API (`backend/api/routes/lab.py`) -- mirrors
// `tasks.ts`/`memory.ts`'s "centralized API client per domain"
// convention.

import { ApiError, request } from "./client";
import type { ExperimentListResponse, ExperimentSummary, LabStatsResponse, SandboxResponse } from "./labTypes";

export { ApiError as LabApiError };

/** `GET /api/v1/lab/experiments` -- real past runs, read off disk. */
export async function listExperiments(): Promise<ExperimentListResponse> {
  return request<ExperimentListResponse>("/api/v1/lab/experiments");
}

/** `POST /api/v1/lab/experiments/perception` -- runs the real synthetic benchmark now. */
export async function runPerceptionExperiment(): Promise<ExperimentSummary> {
  return request<ExperimentSummary>("/api/v1/lab/experiments/perception", { method: "POST" });
}

/** `POST /api/v1/lab/sandbox` -- real parse+plan dry run, never touches the simulator. */
export async function runSandbox(instruction: string, plannerType = "rule_based"): Promise<SandboxResponse> {
  return request<SandboxResponse>("/api/v1/lab/sandbox", {
    method: "POST",
    body: JSON.stringify({ instruction, planner_type: plannerType }),
  });
}

/** `GET /api/v1/lab/stats` -- real aggregate stats, no client-side estimation. */
export async function getLabStats(): Promise<LabStatsResponse> {
  return request<LabStatsResponse>("/api/v1/lab/stats");
}

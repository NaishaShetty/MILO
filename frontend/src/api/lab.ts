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

export interface ModelStatus {
  name: string;
  title: string;
  available: boolean;
  version?: string | null;
  /** Only the outcome predictor can be switched from the Lab; the others are read-only. */
  mode?: "off" | "shadow" | "on";
  metrics?: { auroc: number; pr_auc: number; brier: number; ece: number } | null;
  trained_on?: number | null;
  date?: string | null;
  shadow?: { compared: number; agree: number; used: number; fallbacks: number } | null;
  latency?: { p50_ms: number; p95_ms: number } | null;
  drift_score?: number | null;
  healthy?: boolean | null;
  problem?: string | null;
  explains: string;
  /** Read-only models: switched on by an environment flag? */
  enabled?: boolean;
  headline?: string | null;
}

/** `GET /api/v1/lab/models` -- which learned models are active and how they are doing. */
export async function getModels(): Promise<{ models: ModelStatus[] }> {
  return request<{ models: ModelStatus[] }>("/api/v1/lab/models");
}

/** `POST /api/v1/lab/models/outcome_predictor` -- switch the model off, to shadow, or on. */
export async function setOutcomeMode(mode: NonNullable<ModelStatus["mode"]>): Promise<{ models: ModelStatus[] }> {
  return request<{ models: ModelStatus[] }>("/api/v1/lab/models/outcome_predictor", {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
}

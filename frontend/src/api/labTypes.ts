// labTypes.ts
//
// Purpose
// -------
// TypeScript types for the Phase 8.2 MILO Lab API
// (`backend/api/routes/lab.py`) -- mirrors `backend/api/models/lab.py`
// field-for-field, reusing `ParsedInstruction` (`api/types.ts`) and
// `PlanningResult` (`api/plannerTypes.ts`) exactly like the backend
// reuses `schemas.task.ParsedInstruction`/`planner.models.PlanningResult`.
import type { ParsedInstruction } from "./types";
import type { PlanningResult } from "./plannerTypes";

export interface ExperimentSummary {
  run_id: string;
  experiment_type: string;
  timestamp: string;
  result: Record<string, unknown>;
}

export interface ExperimentListResponse {
  experiments: ExperimentSummary[];
}

export interface SandboxResponse {
  parsed: ParsedInstruction;
  plan: PlanningResult | null;
  unsupported_reason: string | null;
}

export interface LabStatsResponse {
  experiments_run: number;
  task_success_rate: number | null;
  total_actions: number;
  memories_created: number;
  tasks_run: number;
}

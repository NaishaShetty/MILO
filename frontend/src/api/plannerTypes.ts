// plannerTypes.ts
//
// Purpose
// -------
// TypeScript types for the Phase 4 Planning API
// (`POST /api/v1/planner/plan`, `/validate`, `/evaluate`) served by
// `backend/api/routes/planner.py`. Mirrors `api/types.ts`'s own
// convention: a *view* of the backend's real Pydantic models
// (`backend/planner/models.py`, `backend/api/models/planner.py`), only
// the fields this UI actually renders -- the backend models remain the
// single source of truth for the wire format.

import type { SingleTask } from "./types";

export type PlannerType = "rule_based" | "react" | "behavior_tree";

// "blocked"/"cancelled" (StepStatus) and "cancelled" (PlanStatus) are
// Phase 5 additions -- set by execution.controller.ExecutionController
// as it runs a plan, never by the Planner itself. See
// `backend/planner/models.py`'s own Phase 5 docstring notes on
// StepStatus/PlanStatus.
export type StepStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "skipped"
  | "blocked"
  | "cancelled";

export type PlanStatus =
  | "draft"
  | "valid"
  | "invalid"
  | "executing"
  | "completed"
  | "failed"
  | "cancelled";

// Mirrors `backend/planner/models.py`'s `PlanStep`.
export interface PlanStep {
  step_id: number;
  action: string;
  target?: string | null;
  parameters: Record<string, unknown>;
  description: string;
  preconditions: string[];
  postconditions: string[];
  status: StepStatus;
}

// Mirrors `backend/planner/models.py`'s `Plan`.
export interface Plan {
  plan_id: string;
  task_id: string;
  planner_type: string;
  goal_summary: Record<string, string | null>;
  steps: PlanStep[];
  status: PlanStatus;
  created_at: number;
  metadata: Record<string, unknown>;
}

export type IssueSeverity = "error" | "warning";

// Mirrors `backend/planner/models.py`'s `ValidationIssue`.
export interface ValidationIssue {
  step_id?: number | null;
  code: string;
  message: string;
  severity: IssueSeverity;
}

// Mirrors `backend/planner/models.py`'s `ValidationResult`.
export interface ValidationResult {
  valid: boolean;
  issues: ValidationIssue[];
  goal_satisfied?: boolean | null;
}

// Mirrors `backend/planner/models.py`'s `PlanningResult`.
export interface PlanningResult {
  success: boolean;
  plan?: Plan | null;
  validation?: ValidationResult | null;
  errors: string[];
  planner_type: string;
  latency_ms: number;
}

// Mirrors `backend/api/models/planner.py`'s `PlannerMetricsResponse`.
export interface PlannerMetrics {
  planner_type: string;
  success: boolean;
  valid: boolean;
  goal_satisfied?: boolean | null;
  latency_ms: number;
  step_count: number;
  invalid_action_count: number;
  redundant_step_count: number;
  error?: string | null;
}

// Mirrors `backend/api/models/planner.py`'s `EvaluateResponse`.
export interface EvaluateResponse {
  task_id: string;
  results: PlannerMetrics[];
}

export interface PlanRequestBody {
  task: SingleTask;
  planner_type?: PlannerType;
}

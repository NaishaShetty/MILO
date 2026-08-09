// executionTypes.ts
//
// Purpose
// -------
// TypeScript types for the Phase 5 Execution API
// (`POST /api/v1/execution/start`, `GET /{id}`, `POST /{id}/cancel`,
// `GET /{id}/steps`, `GET /{id}/events`) served by
// `backend/api/routes/execution.py`. Mirrors `plannerTypes.ts`'s own
// convention: a *view* of the backend's real Pydantic models
// (`backend/execution/models.py`, `backend/execution/errors.py`), only
// the fields this UI actually renders.

import type { Plan, StepStatus } from "./plannerTypes";

export type ExecutionStatus = "pending" | "running" | "success" | "failed" | "cancelled";

export type ExecutionErrorCode =
  | "INVALID_ACTION"
  | "INVALID_PARAMETER"
  | "PRECONDITION_FAILED"
  | "OBJECT_NOT_FOUND"
  | "TARGET_NOT_FOUND"
  | "OBJECT_NOT_REACHABLE"
  | "NAVIGATION_FAILED"
  | "SIMULATOR_ERROR"
  | "ACTION_TIMEOUT"
  | "EXECUTION_CANCELLED"
  | "VALIDATION_FAILED"
  | "UNKNOWN_ERROR";

// Mirrors `backend/execution/errors.py`'s `ExecutionError`.
export interface ExecutionError {
  code: ExecutionErrorCode;
  message: string;
  step_id?: number | null;
  action?: string | null;
  recoverable: boolean;
  details: Record<string, unknown>;
}

// Mirrors `backend/execution/models.py`'s `ActionResult`.
export interface ActionResult {
  success: boolean;
  action: string;
  action_id: string;
  step_id?: number | null;
  object_id?: string | null;
  target_id?: string | null;
  error?: string | null;
  error_code?: ExecutionErrorCode | null;
  metadata: Record<string, unknown>;
  duration_ms: number;
  retry_count: number;
  timestamp: number;
}

// Mirrors `backend/execution/models.py`'s `StepExecutionRecord`.
export interface StepExecutionRecord {
  step_id: number;
  action: string;
  target?: string | null;
  status: StepStatus;
  result?: ActionResult | null;
  error?: ExecutionError | null;
}

// Mirrors `backend/execution/models.py`'s `ExecutionEvent`.
export interface ExecutionEvent {
  timestamp: number;
  execution_id: string;
  plan_id: string;
  step_id?: number | null;
  action: string;
  target?: string | null;
  status: string;
  duration_ms?: number | null;
  error_code?: ExecutionErrorCode | null;
  message?: string | null;
}

// Mirrors `backend/execution/models.py`'s `ExecutionRecord`.
export interface ExecutionRecord {
  execution_id: string;
  plan_id: string;
  task_id: string;
  status: ExecutionStatus;
  step_results: StepExecutionRecord[];
  events: ExecutionEvent[];
  error?: ExecutionError | null;
  started_at?: number | null;
  finished_at?: number | null;
}

export interface StartExecutionRequestBody {
  plan: Plan;
  max_step_retries?: number;
  step_timeout_s?: number | null;
}

export const TERMINAL_EXECUTION_STATUSES: ExecutionStatus[] = [
  "success",
  "failed",
  "cancelled",
];

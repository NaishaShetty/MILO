// types.ts
//
// Purpose
// -------
// TypeScript types for the Phase 3.7 API contract
// (`POST /api/v1/language/parse`, `GET /health`) served by
// `backend/api/`. These are a *view* of the backend's Pydantic models
// (`backend/schemas/task.py`, `backend/api/models/language.py`) --
// only the fields this UI actually renders, not a field-for-field
// port of the Python schema. The backend's Pydantic models remain the
// single source of truth for the wire format; if a field used here is
// renamed or removed there, `backend/docs/language_interface_spec.md`
// section 30 documents the compatibility process that must accompany
// that change, and this file must be updated to match.
//
// Why `TaskAttributes`/`TaskConstraint`/`SingleTask` are duplicated in
// shape (not literally imported) from Python
// -----------------------------------------------------------------------
// TypeScript cannot import a Python module. Keeping these types
// minimal and explicit here -- rather than trying to auto-generate a
// full mirror of every backend field, most of which this UI never
// displays (e.g. `metadata.source`) -- is the deliberate choice this
// project's Phase 3.7 requirements ask for ("do NOT blindly duplicate
// the entire Pydantic implementation").

export type TaskType = "single" | "multi";

export interface TaskAttributes {
  color?: string | null;
  size?: string | null;
  material?: string | null;
  state?: string | null;
  quantity?: number | null;
  descriptors?: string[] | null;
}

export interface TaskConstraint {
  constraint_type: string;
  description: string;
  value?: string | null;
}

// The fields common to every task representation
// (`backend/schemas/task.py`'s `Task` base class) that this UI
// displays.
interface TaskCommon {
  task_id: string;
  goal?: string | null;
  attributes?: TaskAttributes | null;
  constraints?: TaskConstraint[] | null;
  priority?: string | null;
  preconditions?: string[] | null;
  postconditions?: string[] | null;
  estimated_goal?: string | null;
  needs_clarification: boolean;
  clarification_reason?: string | null;
}

export interface SingleTask extends TaskCommon {
  task_type: "single";
  object?: string | null;
  target?: string | null;
  source_location?: string | null;
  target_location?: string | null;
}

export interface MultiTask extends TaskCommon {
  task_type: "multi";
  subtasks: SingleTask[];
}

// Mirrors `backend/schemas/task.py`'s `ParsedInstruction` discriminated
// union (`task_type` as discriminator).
export type ParsedInstruction = SingleTask | MultiTask;

// Mirrors `backend/api/models/language.py`'s `ParseDiagnostics`.
export interface ParseDiagnostics {
  provider?: string | null;
  model?: string | null;
  prompt_version?: string | null;
  schema_version?: string | null;
  attempt_count: number;
  latency_ms?: number | null;
  recovered: boolean;
}

export type ParseStatus = "ok" | "clarification_required";

// Mirrors `backend/api/models/language.py`'s `ParseResponse`.
export interface ParseResponse {
  status: ParseStatus;
  result: ParsedInstruction;
  diagnostics?: ParseDiagnostics | null;
}

// Machine-readable failure categories the backend's error mapper
// (`backend/api/routes/language.py`'s `_map_language_runtime_error`)
// can return. Kept as a union of the closed set documented there,
// plus a catch-all so an unrecognized future category still
// type-checks.
export type ErrorCategory =
  | "invalid_request"
  | "timeout"
  | "provider_unavailable"
  | "configuration_error"
  | "upstream_invalid_response"
  | "internal_error"
  | (string & {});

// Mirrors `backend/api/models/language.py`'s `ErrorResponse`.
export interface ApiErrorBody {
  category: ErrorCategory;
  message: string;
}

export interface HealthResponse {
  status: string;
  llm_provider_configured: boolean;
}

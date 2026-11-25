// tasksTypes.ts
//
// Purpose
// -------
// TypeScript types for the Phase 7 Task/Orchestrator API
// (`POST /api/v1/tasks`, `GET /api/v1/tasks`, `GET /{id}`, `/state`,
// `/plan`, `/memory`, `/events`, `POST /{id}/cancel`) served by
// `backend/api/routes/tasks.py`. Mirrors `executionTypes.ts`'s own
// convention: a *view* of `backend/agents/task_state.py::TaskState.
// to_dict()`, `backend/agents/events.py::Event`, and
// `backend/agents/failures.py::AgentFailure` -- only the fields this
// UI renders, not a mechanical field-for-field port.

import type { Plan } from "./plannerTypes";
import type { ExecutionRecord } from "./executionTypes";

export type InputSource = "text" | "speech";

// Mirrors `backend/agents/task_state.py`'s `TaskStatus`.
export type TaskStatus =
  | "created"
  | "parsing"
  | "retrieving_memory"
  | "planning"
  | "executing"
  | "reflecting"
  | "replanning"
  | "succeeded"
  | "failed"
  | "cancelled";

export const TERMINAL_TASK_STATUSES: TaskStatus[] = ["succeeded", "failed", "cancelled"];

// Mirrors `backend/agents/contracts.py`'s `AgentState`.
export type AgentStateValue = "idle" | "active" | "thinking" | "waiting" | "error" | "shutdown";

// Mirrors `backend/agents/failures.py`'s `FailureCategory`.
export type FailureCategory =
  | "VISION_FAILURE"
  | "OBJECT_NOT_FOUND"
  | "OBJECT_NOT_VISIBLE"
  | "NAVIGATION_FAILURE"
  | "PATH_BLOCKED"
  | "ACTION_FAILURE"
  | "INVALID_ACTION"
  | "INVALID_PLAN"
  | "ENVIRONMENT_CHANGED"
  | "MEMORY_FAILURE"
  | "TIMEOUT"
  | "UNKNOWN_FAILURE";

// Mirrors `backend/agents/failures.py`'s `AgentFailure`.
export interface AgentFailure {
  category: FailureCategory;
  message: string;
  agent: string;
  recoverable: boolean;
  details: Record<string, unknown>;
}

// Mirrors `backend/agents/events.py`'s `EventType`.
export type EventType =
  | "TASK_CREATED"
  | "TASK_PARSED"
  | "MEMORY_RETRIEVED"
  | "PLAN_CREATED"
  | "OBSERVATION_RECEIVED"
  | "ACTION_STARTED"
  | "ACTION_COMPLETED"
  | "ACTION_FAILED"
  | "REFLECTION_COMPLETED"
  | "REPLAN_TRIGGERED"
  | "MEMORY_UPDATED"
  | "TASK_COMPLETED"
  | "TASK_FAILED"
  | "TASK_CANCELLED";

// Mirrors `backend/agents/events.py`'s `Event`.
export interface TaskEvent {
  event_id: string;
  task_id: string;
  agent: string;
  event: EventType;
  timestamp: number;
  payload: Record<string, unknown>;
  latency_ms: number | null;
}

// `TaskState.to_dict()`'s `latencies_ms` -- only keys the orchestrator
// actually populates ever appear; a stage the task never reached has
// no key (never a fabricated 0).
export interface TaskLatenciesMs {
  memory_retrieval_ms?: number;
  planning_ms?: number;
  vision_ms?: number;
  execution_ms?: number;
  memory_write_ms?: number;
  total_ms?: number;
}

// `TaskState.metrics()`'s exact return shape.
export interface TaskMetrics {
  actions: number;
  failures: number;
  replans: number;
  attempts: number;
  success: boolean;
  total_ms: number | null;
}

// A `TaskState.retrieved_memories`/`created_memories` entry --
// `Dict[str, Any]` on the backend (see that field's own docstring: no
// fixed schema is guaranteed), so this is deliberately loose with a
// few commonly-populated fields called out.
export interface TaskMemoryEntry {
  memory_id?: string;
  memory_type?: string;
  content?: string;
  confidence?: number;
  [key: string]: unknown;
}

// Mirrors `backend/agents/task_state.py`'s `TaskState.to_dict()`.
export interface TaskState {
  task_id: string;
  user_request: string;
  input_source: InputSource;
  goal: string | null;
  objects: string[];
  target: string | null;
  current_location: string | null;
  current_plan: Plan | null;
  /** Set while MILO waits for an approve / skip / edit answer. */
  pending_decision?: PendingDecision | null;
  /** The user's own words, when the task came from a sentence. */
  instruction?: string | null;
  current_step: number | null;
  observations: Record<string, unknown>[];
  known_objects: string[];
  completed_steps: number[];
  execution_history: ExecutionRecord[];
  failures: AgentFailure[];
  retrieved_memories: TaskMemoryEntry[];
  agent_states: Record<string, AgentStateValue>;
  status: TaskStatus;
  latencies_ms: TaskLatenciesMs;
  created_memories: TaskMemoryEntry[];
  metrics: TaskMetrics;
  /** A plain-language result beyond "it worked" (where a find found it, "The table is already clear."). */
  answer?: string | null;
  /** The single-object sub-goals a multi-object task ran, in order. */
  sub_goals?: SubGoal[];
  /** What MILO learned from the mission, as sentences. */
  learned?: string[];
  /** The planner that ran: rule_based | react | behavior_tree | htn, or "novel" when MILO worked the task out itself. */
  planner?: PlannerChoice | "novel" | null;
  /** Set when the planner did not do exactly what was asked (e.g. fell back). */
  planner_note?: string | null;
  cancel_requested?: boolean;
  cancel_summary?: string | null;
  /** MILO's running commentary, oldest first. */
  thoughts?: TaskThought[];
  created_at?: number;
}

export type PlannerChoice = "rule_based" | "react" | "behavior_tree" | "htn";

export interface SubGoal {
  goal: string | null;
  object: string | null;
  target: string | null;
}

export type ThoughtKind = "memory" | "planner" | "eyes" | "hands" | "reflect";

export interface TaskThought {
  kind: ThoughtKind;
  text: string;
  at: number;
  step_id: number | null;
}

/** One row of `GET /tasks/stream` -- enough for a recent-missions card. */
export interface TaskSummary {
  task_id: string;
  user_request: string;
  goal: string | null;
  status: TaskStatus;
  planner: PlannerChoice | "novel" | null;
  current_step: number | null;
  answer: string | null;
  cancel_requested: boolean;
  success: boolean;
  created_at: number;
  steps: number;
  completed_steps: number;
  memories_used: number;
  replans: number;
  total_ms: number | null;
}

/**
 * What `POST /tasks` answers. A request becomes a running task (`kind:
 * "task"`, plus the usual TaskState), or MILO replies without starting
 * anything: `answer` (a question or help), `remembered` (a preference),
 * `clarify` (a question back), or `unsupported` (a plain reason).
 */
export type CreateTaskResult =
  | (TaskState & { kind: "task"; understood_as: string })
  | { kind: "answer"; answer: string; understood_as?: string; library?: TaskKind[] }
  | { kind: "remembered" | "not_remembered"; message: string; understood_as?: string }
  | { kind: "clarify" | "unsupported"; message: string; details?: Record<string, unknown>; choices?: ReplyChoice[] };

/** A tappable answer to MILO's question: send `instruction` (pinned to `object_id`). */
export interface ReplyChoice {
  label: string;
  instruction: string;
  object_id?: string;
}

/** What MILO is waiting for the user to decide (a risky step, or a plan it worked out). */
export interface PendingDecision {
  kind: "step" | "plan";
  why: string;
  step_id?: number;
  action?: string;
  target?: string | null;
  text?: string;
  steps?: Array<{ step_id: number; action: string; target: string | null; container?: string | null; text: string }>;
  asked_at?: number;
}

/** One entry of the task library (`GET /tasks/library`). */
export interface TaskKind {
  id: string;
  title: string;
  summary: string;
  examples: string[];
  goals: string[];
  composite: boolean;
}

// `GET /{task_id}/memory`'s response shape.
export interface TaskMemoryResponse {
  retrieved: TaskMemoryEntry[];
  created: TaskMemoryEntry[];
}

export interface CreateTaskRequestBody {
  instruction: string;
  input_source?: InputSource;
  planner?: PlannerChoice;
  /** The answer to "which one?": pins the object to one simulator id. */
  object_id?: string;
}

// `GET /{task_id}/robot`'s response shape -- a curated view of AI2-THOR's
// raw metadata (see `backend/api/routes/tasks.py::get_task_robot_state`).
// `position`/`rotation`/`camera_horizon` are `null` when the simulator
// hasn't reported an agent pose yet.
export interface RobotVisibleObject {
  object_id: string | null;
  object_type: string | null;
  position: { x: number; y: number; z: number } | null;
  distance: number | null;
}

export interface RobotHeldObject {
  object_id: string | null;
  object_type: string | null;
}

export interface RobotState {
  position: { x: number; y: number; z: number } | null;
  rotation: { x: number; y: number; z: number } | null;
  camera_horizon: number | null;
  held_object: RobotHeldObject | null;
  visible_objects: RobotVisibleObject[];
}

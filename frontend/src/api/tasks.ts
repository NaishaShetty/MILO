// tasks.ts
//
// Purpose
// -------
// The *only* place in this frontend that issues an HTTP request to the
// backend's Phase 7 Task/Orchestrator API (`backend/api/routes/
// tasks.py`) -- mirrors `execution.ts`'s "centralized API client per
// domain" convention. This is the sole path by which the frontend ever
// creates a task: both the text input and the transcribed-speech flow
// (`speech.ts` -> `createTask()`) call `createTask()` here, so there is
// exactly one task-creation pipeline end to end (see this project's
// "do not build a second speech/task pipeline" rule).

import { ApiError, request } from "./client";
import type {
  CreateTaskRequestBody,
  CreateTaskResult,
  PlannerChoice,
  RobotState,
  TaskEvent,
  TaskKind,
  TaskMemoryResponse,
  TaskState,
} from "./tasksTypes";
import type { Plan } from "./plannerTypes";

export { ApiError as TasksApiError };

/**
 * `POST /api/v1/tasks`. Returns immediately (202) with the task's
 * initial `TaskState` -- the Orchestrator continues running it on the
 * backend; poll `getTask()` for progress. Throws `ApiError` for 409
 * (another task already running), 422 (empty/multi-task instruction),
 * or 503 (no simulator).
 */
export async function createTask(
  instruction: string,
  inputSource: CreateTaskRequestBody["input_source"] = "text",
  planner?: PlannerChoice,
  objectId?: string,
): Promise<CreateTaskResult> {
  const body: CreateTaskRequestBody = { instruction, input_source: inputSource };
  if (planner) body.planner = planner;
  if (objectId) body.object_id = objectId;
  return request<CreateTaskResult>("/api/v1/tasks", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** `GET /api/v1/tasks/library` -- everything MILO knows how to do, with examples. */
export async function getTaskLibrary(): Promise<TaskKind[]> {
  return request<TaskKind[]>("/api/v1/tasks/library");
}

/** `GET /api/v1/tasks` -- every task this backend process has run, newest first. */
export async function listTasks(): Promise<TaskState[]> {
  return request<TaskState[]>("/api/v1/tasks");
}

/** `GET /api/v1/tasks/{id}` -- the current `TaskState`. */
export async function getTask(taskId: string): Promise<TaskState> {
  return request<TaskState>(`/api/v1/tasks/${encodeURIComponent(taskId)}`);
}

/** `GET /api/v1/tasks/{id}/plan` -- the task's current `Plan`, or `null` before one exists. */
export async function getTaskPlan(taskId: string): Promise<Plan | null> {
  return request<Plan | null>(`/api/v1/tasks/${encodeURIComponent(taskId)}/plan`);
}

/** `GET /api/v1/tasks/{id}/memory` -- memories retrieved/created for this task. */
export async function getTaskMemory(taskId: string): Promise<TaskMemoryResponse> {
  return request<TaskMemoryResponse>(`/api/v1/tasks/${encodeURIComponent(taskId)}/memory`);
}

/**
 * `GET /api/v1/tasks/{id}/robot` -- the shared simulator's current
 * position/rotation/held-object/visible-objects. Throws `ApiError`
 * (503, category `execution_unavailable`) when no simulator is running --
 * callers should treat that as "simulator not connected," not a generic
 * error.
 */
export async function getTaskRobotState(taskId: string): Promise<RobotState> {
  return request<RobotState>(`/api/v1/tasks/${encodeURIComponent(taskId)}/robot`);
}

/** `GET /api/v1/tasks/{id}/events` -- the structured event log. */
export async function getTaskEvents(taskId: string): Promise<TaskEvent[]> {
  return request<TaskEvent[]>(`/api/v1/tasks/${encodeURIComponent(taskId)}/events`);
}

/** `POST /api/v1/tasks/{id}/cancel` -- requests cancellation; safe to call on a finished task. */
export async function cancelTask(taskId: string): Promise<TaskState> {
  return request<TaskState>(`/api/v1/tasks/${encodeURIComponent(taskId)}/cancel`, {
    method: "POST",
  });
}

/** `POST /api/v1/tasks/{id}/decision` -- answer a risky-step or plan question. */
export async function decide(
  taskId: string,
  choice: "approve" | "skip" | "cancel",
  steps?: Array<{ step_id: number }>,
): Promise<TaskState> {
  return request<TaskState>(`/api/v1/tasks/${taskId}/decision`, {
    method: "POST",
    body: JSON.stringify(steps ? { choice, steps } : { choice }),
  });
}

/** `GET /api/v1/tasks/{id}/undo` -- what undoing would do, and what can't be undone. */
export async function undoPreview(
  taskId: string,
): Promise<{ steps: Array<{ action: string; target: string | null }>; cannot_undo: string[]; possible: boolean }> {
  return request(`/api/v1/tasks/${taskId}/undo`);
}

/** `POST /api/v1/tasks/{id}/undo` -- start the undo mission. */
export async function undoTask(taskId: string): Promise<TaskState & { cannot_undo: string[] }> {
  return request(`/api/v1/tasks/${taskId}/undo`, { method: "POST" });
}

/** `POST /api/v1/tasks/{id}/correct` -- "no, the other one". */
export async function correctTask(taskId: string): Promise<TaskState> {
  return request(`/api/v1/tasks/${taskId}/correct`, { method: "POST", body: "{}" });
}

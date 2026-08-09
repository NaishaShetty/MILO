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
  TaskEvent,
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
): Promise<TaskState> {
  return request<TaskState>("/api/v1/tasks", {
    method: "POST",
    body: JSON.stringify({ instruction, input_source: inputSource }),
  });
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

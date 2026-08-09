// useTaskHistory.ts
//
// Purpose
// -------
// Shared "every task this backend has run" data source, built on
// `GET /api/v1/tasks` (added for Session 3 specifically so this hook
// -- and the Home/Memory/Activity/MILO Lab pages that use it --
// doesn't need to fabricate cross-task history/statistics; see
// `backend/api/routes/tasks.py::list_tasks`). Extracted once instead
// of four pages independently polling the same endpoint.
import { useCallback } from "react";

import { listTasks } from "../api/tasks";
import type { TaskState } from "../api/tasksTypes";
import { usePolling } from "./usePolling";

const POLL_INTERVAL_MS = 5000;

export interface TaskHistoryResult {
  /** Newest first, per `GET /tasks`'s own ordering. Empty (not null) once loaded with no tasks. */
  tasks: TaskState[];
  status: "idle" | "loading" | "success" | "error";
  error: unknown;
  refresh: () => void;
}

/**
 * Polls the full task list on a slow interval (this is history, not a
 * live single-task view -- `TaskContext`'s active-task polling is what
 * needs a fast interval). `enabled` lets a page opt out entirely
 * (e.g. a page not currently mounted); defaults to on.
 */
export function useTaskHistory(enabled = true): TaskHistoryResult {
  const fetcher = useCallback(() => listTasks(), []);
  const { data, status, error, refresh } = usePolling(fetcher, {
    intervalMs: POLL_INTERVAL_MS,
    enabled,
  });
  return { tasks: data ?? [], status, error, refresh };
}

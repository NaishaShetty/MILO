// useActivityEvents.ts
//
// Purpose
// -------
// Merges every loaded task's event log (`GET /tasks/{id}/events`) into
// one timestamp-sorted list for the Activity page -- `TaskContext`
// only polls events for the single *active* task, so this is a
// separate, page-scoped fetch. Bounded to the 20 most recent tasks
// (matches `MemoryPage`'s own bound) so this can't fan out into an
// unbounded number of requests as history grows.
import { useEffect, useState } from "react";

import { getTaskEvents } from "../api/tasks";
import type { TaskEvent, TaskState } from "../api/tasksTypes";

const MAX_TASKS = 20;

export interface ActivityEventsResult {
  events: TaskEvent[];
  status: "idle" | "loading" | "success" | "error";
}

export function useActivityEvents(tasks: TaskState[]): ActivityEventsResult {
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");

  const taskIds = tasks
    .slice(0, MAX_TASKS)
    .map((task) => task.task_id)
    .join(",");

  useEffect(() => {
    if (taskIds.length === 0) {
      setEvents([]);
      setStatus("success");
      return;
    }

    let cancelled = false;
    setStatus((previous) => (previous === "idle" ? "loading" : previous));

    Promise.all(
      taskIds.split(",").map((taskId) =>
        getTaskEvents(taskId).catch(() => [] as TaskEvent[]),
      ),
    ).then((results) => {
      if (cancelled) return;
      const merged = results.flat().sort((a, b) => b.timestamp - a.timestamp);
      setEvents(merged);
      setStatus("success");
    });

    return () => {
      cancelled = true;
    };
  }, [taskIds]);

  return { events, status };
}

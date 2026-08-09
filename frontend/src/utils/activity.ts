// activity.ts (frontend/src/utils)
//
// Purpose
// -------
// Filtering/search/export helpers for the Activity page, built from
// the *real* `EventType` vocabulary (`backend/agents/events.py`), not
// the spec screenshot's illustrative filter list verbatim. Two of the
// spec's example categories don't map cleanly onto anything the
// backend actually publishes: there is no distinct "Navigation" event
// type (navigation happens inside the single `ACTION_STARTED`/plan-
// execution step, indistinguishable at the event-type level -- see
// `backend/orchestration/orchestrator.py`'s `_publish` call sites),
// and every event's `agent` field is literally the string
// `"orchestrator"` (all events are published from one place in that
// file) -- so filtering by `agent` would silently show nothing useful.
// Categories below are grouped by `EventType` instead, which is real
// and stable; a category with a real definition but zero current
// matches (e.g. "Reflection" until `REFLECTION_COMPLETED` is actually
// emitted) is still listed -- an empty result is not a fake one.
import type { EventType, TaskEvent } from "../api/tasksTypes";

export interface ActivityCategory {
  id: string;
  label: string;
  eventTypes: EventType[] | null; // null = "All"
}

export const ACTIVITY_CATEGORIES: ActivityCategory[] = [
  { id: "all", label: "All", eventTypes: null },
  {
    id: "tasks",
    label: "Tasks",
    eventTypes: ["TASK_CREATED", "TASK_PARSED", "TASK_COMPLETED", "TASK_FAILED", "TASK_CANCELLED"],
  },
  { id: "perception", label: "Perception", eventTypes: ["OBSERVATION_RECEIVED"] },
  { id: "planning", label: "Planning", eventTypes: ["PLAN_CREATED", "REPLAN_TRIGGERED"] },
  { id: "execution", label: "Execution", eventTypes: ["ACTION_STARTED", "ACTION_COMPLETED", "ACTION_FAILED"] },
  { id: "memory", label: "Memory", eventTypes: ["MEMORY_RETRIEVED", "MEMORY_UPDATED"] },
  { id: "reflection", label: "Reflection", eventTypes: ["REFLECTION_COMPLETED"] },
  { id: "errors", label: "Errors", eventTypes: ["ACTION_FAILED", "TASK_FAILED"] },
];

export function filterByCategory(events: TaskEvent[], categoryId: string): TaskEvent[] {
  const category = ACTIVITY_CATEGORIES.find((entry) => entry.id === categoryId);
  if (!category || category.eventTypes === null) return events;
  const allowed = new Set<string>(category.eventTypes);
  return events.filter((event) => allowed.has(event.event));
}

/** Matches `event`, `agent`, `task_id`, or JSON-stringified `payload` against `query` (case-insensitive). */
export function searchEvents(events: TaskEvent[], query: string): TaskEvent[] {
  const trimmed = query.trim().toLowerCase();
  if (!trimmed) return events;
  return events.filter((event) => {
    const haystack = [event.event, event.agent, event.task_id, JSON.stringify(event.payload)]
      .join(" ")
      .toLowerCase();
    return haystack.includes(trimmed);
  });
}

/** Serializes `events` to a downloadable JSON file -- a real export of whatever is currently loaded/filtered. */
export function exportEventsAsJson(events: TaskEvent[]): void {
  const blob = new Blob([JSON.stringify(events, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `milo-activity-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

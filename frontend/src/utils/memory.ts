// memory.ts (frontend/src/utils)
//
// Purpose
// -------
// Pure helpers that turn `TaskContext.history` (every `TaskState` this
// backend has run, each already carrying its own real
// `retrieved_memories`/`created_memories` -- see
// `backend/agents/task_state.py`) into the aggregated views the Memory
// page needs (recent memories, per-type counts, a "knowledge" list).
// No backend memory-search endpoint exists (see Session 3 audit
// notes), so this is real per-task memory data assembled client-side,
// not a fabricated search -- kept as pure functions, separate from
// `MemoryPage.tsx`, so this aggregation logic is unit-testable without
// rendering React.
import type { TaskMemoryEntry, TaskState } from "../api/tasksTypes";

export type MemorySource = "retrieved" | "created";

export interface AggregatedMemory extends TaskMemoryEntry {
  task_id: string;
  source: MemorySource;
}

// Mirrors `backend/memory/models.py`'s `MemoryType` -- "semantic",
// "episodic", "failure", "user". The spec's "Things I Learned"
// category has no distinct backend type; memories of that flavor
// belong to "semantic"/"episodic" on the backend already, so this
// frontend does not invent a fifth type.
export const MEMORY_CATEGORY_LABELS: Record<string, string> = {
  semantic: "Things I Know",
  episodic: "Experiences",
  failure: "Things That Went Wrong",
  user: "Your Preferences",
};

/**
 * Flattens every task's `retrieved_memories`/`created_memories` into
 * one list, newest task first (matching `history`'s own order --
 * `GET /tasks` is already newest-first). When the same `memory_id`
 * appears more than once (e.g. retrieved by one task, created by
 * another), the first occurrence wins and later ones are dropped, so
 * statistics count distinct memories, not per-task references.
 */
export function aggregateMemories(history: TaskState[]): AggregatedMemory[] {
  const seen = new Set<string>();
  const result: AggregatedMemory[] = [];

  for (const task of history) {
    for (const entry of task.created_memories) {
      addUnique(result, seen, { ...entry, task_id: task.task_id, source: "created" });
    }
    for (const entry of task.retrieved_memories) {
      addUnique(result, seen, { ...entry, task_id: task.task_id, source: "retrieved" });
    }
  }
  return result;
}

function addUnique(
  result: AggregatedMemory[],
  seen: Set<string>,
  entry: AggregatedMemory,
): void {
  const key = entry.memory_id ?? `${entry.task_id}:${entry.source}:${result.length}`;
  if (seen.has(key)) return;
  seen.add(key);
  result.push(entry);
}

/** Counts distinct memories per `memory_type`. Unknown/missing types are grouped under `"unknown"`. */
export function countsByType(entries: AggregatedMemory[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const entry of entries) {
    const type = entry.memory_type ?? "unknown";
    counts[type] = (counts[type] ?? 0) + 1;
  }
  return counts;
}

/** Every entry whose `memory_type` is `"semantic"` -- the closest real analogue to "My Knowledge." */
export function semanticKnowledge(entries: AggregatedMemory[]): AggregatedMemory[] {
  return entries.filter((entry) => entry.memory_type === "semantic");
}

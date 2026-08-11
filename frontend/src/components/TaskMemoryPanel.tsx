// TaskMemoryPanel.tsx
//
// Purpose
// -------
// Mission Control's "Memory for this Task" panel (Phase 8.6 spec
// section 12): shows the real memories retrieved for, and created by,
// the active task via `GET /api/v1/tasks/{id}/memory` (already exists,
// `tasks.ts::getTaskMemory` -- backed by `TaskState.retrieved_memories`/
// `created_memories`). Polls independently of `TaskContext` (small,
// infrequent payload) the same way `AgentsContext`/`usePolling` do
// elsewhere. When nothing was retrieved, renders the literal
// "No relevant memory retrieved." required by spec section 12 --
// never invents an entry to fill the panel.
import { useCallback } from "react";

import { getTaskMemory } from "../api/tasks";
import type { TaskMemoryEntry } from "../api/tasksTypes";
import { usePolling } from "../hooks/usePolling";

const POLL_INTERVAL_MS = 4000;

function MemoryRow({ entry }: { entry: TaskMemoryEntry }) {
  return (
    <li className="task-memory-panel__item">
      {entry.memory_type && (
        <span className="task-memory-panel__item-type">{entry.memory_type}</span>
      )}
      <span>{entry.content ?? entry.memory_id ?? "(no content)"}</span>
    </li>
  );
}

interface TaskMemoryPanelProps {
  taskId: string | null;
}

export function TaskMemoryPanel({ taskId }: TaskMemoryPanelProps) {
  const fetcher = useCallback(() => {
    if (!taskId) return Promise.reject(new Error("no active task"));
    return getTaskMemory(taskId);
  }, [taskId]);

  const { data, status } = usePolling(fetcher, {
    intervalMs: POLL_INTERVAL_MS,
    enabled: taskId !== null,
  });

  if (!taskId) {
    return <p className="task-memory-panel__empty">No mission selected yet.</p>;
  }

  if (status === "loading" || status === "idle") {
    return <p className="task-memory-panel__empty">Loading memory...</p>;
  }

  const retrieved = data?.retrieved ?? [];
  const created = data?.created ?? [];

  return (
    <div className="task-memory-panel">
      <section className="task-memory-panel__section" aria-label="Retrieved memory">
        <h4 className="task-memory-panel__heading">Retrieved</h4>
        {retrieved.length === 0 ? (
          <p className="task-memory-panel__empty">No relevant memory retrieved.</p>
        ) : (
          <ul className="task-memory-panel__list">
            {retrieved.map((entry, index) => (
              <MemoryRow key={entry.memory_id ?? index} entry={entry} />
            ))}
          </ul>
        )}
      </section>
      <section className="task-memory-panel__section" aria-label="New memory">
        <h4 className="task-memory-panel__heading">Newly Created</h4>
        {created.length === 0 ? (
          <p className="task-memory-panel__empty">No new memory created yet.</p>
        ) : (
          <ul className="task-memory-panel__list">
            {created.map((entry, index) => (
              <MemoryRow key={entry.memory_id ?? index} entry={entry} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

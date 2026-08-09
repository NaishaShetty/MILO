// ExecutionLog.tsx
//
// Purpose
// -------
// Renders one execution's `ExecutionEvent[]` as a timestamped log --
// section 11/16's "Execution log" panel
// (`12:02:01 ✓ Locate Apple`). Purely a view of
// `execution.models.ExecutionEvent`; no polling or state of its own.
import type { ExecutionEvent } from "../api/executionTypes";

const STATUS_ICON: Record<string, string> = {
  started: "→",
  success: "✓",
  failed: "✗",
  blocked: "⛔",
  skipped: "⊘",
  cancelled: "⊗",
};

function formatTime(timestampSeconds: number): string {
  return new Date(timestampSeconds * 1000).toLocaleTimeString();
}

interface ExecutionLogProps {
  events: ExecutionEvent[];
}

export function ExecutionLog({ events }: ExecutionLogProps) {
  if (events.length === 0) {
    return <p className="execution-log__empty">No execution events yet.</p>;
  }

  return (
    <ul className="execution-log">
      {events.map((event, index) => (
        <li key={index} className="execution-log__item">
          <span className="execution-log__time">{formatTime(event.timestamp)}</span>
          <span className="execution-log__icon" aria-hidden="true">
            {STATUS_ICON[event.status] ?? "•"}
          </span>
          <span className="execution-log__text">
            {event.action}
            {event.target ? ` ${event.target}` : ""}
            {event.message ? ` -- ${event.message}` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}

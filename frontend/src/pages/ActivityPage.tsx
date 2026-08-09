// ActivityPage.tsx
//
// Purpose
// -------
// "What has MILO been doing?" -- a merged, filterable, searchable feed
// of every real event from `GET /tasks/{id}/events` across the recent
// tasks in `TaskContext.history` (`useActivityEvents`). Filtering/
// search/export logic lives in `utils/activity.ts` (unit-tested there)
// so this component stays pure rendering + selection state.
//
// Phase 8.2 visual pass: left sidebar (per-category counts, a real
// "Summary" panel) + center feed + right detail panel, matching the
// Activity mockup's 3-column composition. Every number in the sidebar
// is computed from `events`/`history`, the same real data already
// rendered in the feed -- never a second, invented statistic.
import { useMemo, useState } from "react";

import { GlassCard } from "../components/GlassCard";
import { StatusPill } from "../components/StatusPill";
import { useTask } from "../state/TaskContext";
import { useActivityEvents } from "../hooks/useActivityEvents";
import { ACTIVITY_CATEGORIES, exportEventsAsJson, filterByCategory, searchEvents } from "../utils/activity";
import type { TaskEvent } from "../api/tasksTypes";

function formatTimestamp(unixSeconds: number): { date: string; time: string } {
  const d = new Date(unixSeconds * 1000);
  return { date: d.toLocaleDateString(), time: d.toLocaleTimeString() };
}

export function ActivityPage() {
  const { history } = useTask();
  const { events, status } = useActivityEvents(history);
  const [category, setCategory] = useState("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<TaskEvent | null>(null);

  const filtered = useMemo(
    () => searchEvents(filterByCategory(events, category), query),
    [events, category, query],
  );

  const categoryCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const entry of ACTIVITY_CATEGORIES) {
      counts.set(entry.id, filterByCategory(events, entry.id).length);
    }
    return counts;
  }, [events]);

  // Real summary, computed from TaskState.metrics() -- never invented
  // (see backend/agents/task_state.py::TaskState.metrics for exactly
  // what each field measures).
  const finishedTasks = history.filter((t) => t.status === "succeeded" || t.status === "failed");
  const tasksCompleted = history.filter((t) => t.status === "succeeded").length;
  const successRate = finishedTasks.length > 0 ? (tasksCompleted / finishedTasks.length) * 100 : null;
  const totalActions = history.reduce((sum, t) => sum + t.metrics.actions, 0);
  const totalReplans = history.reduce((sum, t) => sum + t.metrics.replans, 0);

  return (
    <main aria-label="Activity" className="activity-page">
      <h1>Activity</h1>

      <div className="activity-page__layout">
        <aside className="activity-page__sidebar">
          <GlassCard title="Filter by Type">
            <div className="activity-page__filters" role="group" aria-label="Filters">
              {ACTIVITY_CATEGORIES.map((entry) => (
                <button
                  key={entry.id}
                  type="button"
                  aria-label={entry.label}
                  className={
                    "activity-page__filter" + (category === entry.id ? " activity-page__filter--active" : "")
                  }
                  onClick={() => setCategory(entry.id)}
                >
                  <span aria-hidden="true">{entry.label}</span>
                  <span className="activity-page__filter-count" aria-hidden="true">
                    {categoryCounts.get(entry.id) ?? 0}
                  </span>
                </button>
              ))}
            </div>
          </GlassCard>

          <GlassCard title="Summary">
            <dl className="activity-page__summary">
              <dt>Tasks Completed</dt>
              <dd>{tasksCompleted}</dd>
              <dt>Success Rate</dt>
              <dd>{successRate != null ? `${successRate.toFixed(0)}%` : "—"}</dd>
              <dt>Total Actions</dt>
              <dd>{totalActions}</dd>
              <dt>Replans</dt>
              <dd>{totalReplans}</dd>
            </dl>
          </GlassCard>
        </aside>

        <section className="activity-page__main">
          <div className="activity-page__toolbar">
            <label htmlFor="activity-search" className="activity-page__search-label">
              Search activity
            </label>
            <input
              id="activity-search"
              type="text"
              placeholder="Search events..."
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <button
              type="button"
              onClick={() => exportEventsAsJson(filtered)}
              disabled={filtered.length === 0}
            >
              Export Log
            </button>
          </div>

          <div className="activity-page__body">
            <GlassCard title="Activity Feed" className="activity-page__feed-card">
              <section aria-label="Activity Feed" className="activity-page__feed">
                {status === "loading" && events.length === 0 && <p>Loading...</p>}
                {status !== "loading" && filtered.length === 0 && <p>No activity yet.</p>}
                {filtered.length > 0 && (
                  <ul className="activity-page__list">
                    {filtered.map((event) => (
                      <li key={event.event_id}>
                        <button
                          type="button"
                          className={
                            "activity-page__item" +
                            (selected?.event_id === event.event_id ? " activity-page__item--selected" : "")
                          }
                          onClick={() => setSelected(event)}
                        >
                          <span className="activity-page__item-time">
                            {formatTimestamp(event.timestamp).time}
                          </span>
                          <span className="activity-page__item-agent">{event.agent}</span>
                          <span className="activity-page__item-event">{event.event}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </GlassCard>

            <GlassCard title="Event Details" className="activity-page__details-card">
              <section aria-label="Event Details">
                {!selected && <p>Select an event to see its details.</p>}
                {selected && (
                  <>
                    <StatusPill tone="accent">{selected.event}</StatusPill>
                    <dl className="activity-page__detail-list">
                      <dt>Time</dt>
                      <dd>{formatTimestamp(selected.timestamp).time}</dd>
                      <dt>Date</dt>
                      <dd>{formatTimestamp(selected.timestamp).date}</dd>
                      <dt>Agent</dt>
                      <dd>{selected.agent}</dd>
                      <dt>Event</dt>
                      <dd>{selected.event}</dd>
                      <dt>Task</dt>
                      <dd>{selected.task_id}</dd>
                      {selected.latency_ms != null && (
                        <>
                          <dt>Latency</dt>
                          <dd>{selected.latency_ms.toFixed(1)} ms</dd>
                        </>
                      )}
                      <dt>Metadata</dt>
                      <dd>
                        <pre className="activity-page__payload">
                          {JSON.stringify(selected.payload, null, 2)}
                        </pre>
                      </dd>
                    </dl>
                  </>
                )}
              </section>
            </GlassCard>
          </div>
        </section>
      </div>
    </main>
  );
}

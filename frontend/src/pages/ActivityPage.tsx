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
// Visual refinement pass: three-column dashboard (filters/summary |
// timeline | event details) matching the Activity mockup's
// composition. Every number/label rendered here still comes straight
// out of `events`/`history`/`ACTIVITY_CATEGORIES` -- this file adds no
// second data source, just a richer renderer for the same real state
// (see the mockup task's "do not fabricate" list: no invented counts,
// timestamps, descriptions, durations, locations, or outcomes).
import { useMemo, useState } from "react";

import { ActivityIcon, ACTIVITY_CATEGORY_TONE } from "../components/ActivityIcons";
import type { ActivityIconName } from "../components/ActivityIcons";
import { GlassCard } from "../components/GlassCard";
import { StatusPill } from "../components/StatusPill";
import { useTask } from "../state/TaskContext";
import { useActivityEvents } from "../hooks/useActivityEvents";
import { ACTIVITY_CATEGORIES, exportEventsAsJson, filterByCategory, searchEvents } from "../utils/activity";
import type { ActivityCategory } from "../utils/activity";
import type { EventType, TaskEvent } from "../api/tasksTypes";

function formatTimestamp(unixSeconds: number): { date: string; time: string } {
  const d = new Date(unixSeconds * 1000);
  return { date: d.toLocaleDateString(), time: d.toLocaleTimeString() };
}

/** "TASK_CREATED" -> "Task Created" -- a faithful reformat of the real
 * `event.event` constant, not an invented description. */
function formatEventLabel(eventType: EventType): string {
  return eventType
    .toLowerCase()
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/** The most specific real category (`ACTIVITY_CATEGORIES`, excluding
 * "All") this event belongs to, for the row's badge -- same
 * classification the sidebar filters already use, just applied to one
 * event instead of counted across all of them. */
function categorizeEvent(event: TaskEvent): ActivityCategory | null {
  return (
    ACTIVITY_CATEGORIES.find((entry) => entry.id !== "all" && entry.eventTypes?.includes(event.event)) ?? null
  );
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
  // what each field measures). "Memories Created" / "Total Time
  // Active" from the reference mockup have no equivalent in this data
  // architecture, so they're omitted rather than faked.
  const finishedTasks = history.filter((t) => t.status === "succeeded" || t.status === "failed");
  const tasksCompleted = history.filter((t) => t.status === "succeeded").length;
  const successRate = finishedTasks.length > 0 ? (tasksCompleted / finishedTasks.length) * 100 : null;
  const totalActions = history.reduce((sum, t) => sum + t.metrics.actions, 0);
  const totalReplans = history.reduce((sum, t) => sum + t.metrics.replans, 0);

  const selectedCategory = selected ? categorizeEvent(selected) : null;
  const selectedTask = selected ? history.find((t) => t.task_id === selected.task_id) ?? null : null;
  // "Today" header's date is the most recent real event's own date, or
  // (with no events yet) today's real client date -- never a
  // hardcoded mockup date.
  const headerDate =
    filtered.length > 0 ? formatTimestamp(filtered[0].timestamp).date : new Date().toLocaleDateString();

  return (
    <main aria-label="Activity" className="activity-page">
      <h1 className="sr-only">Activity</h1>

      <header className="activity-page__header">
        <div>
          <p className="activity-page__title">
            Activity Feed <span className="activity-page__title-dot" aria-hidden="true" />
          </p>
          <p className="activity-page__subtitle">A timeline of everything I've seen, thought, and done.</p>
        </div>

        <div className="activity-page__toolbar">
          <div className="activity-page__search">
            <label htmlFor="activity-search" className="activity-page__search-label">
              Search activity
            </label>
            <input
              id="activity-search"
              type="text"
              placeholder="Search activity..."
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <ActivityIcon name="search" className="activity-page__search-icon" />
          </div>
          <button
            type="button"
            className="activity-page__export"
            onClick={() => exportEventsAsJson(filtered)}
            disabled={filtered.length === 0}
          >
            <ActivityIcon name="download" />
            <span>Export Log</span>
          </button>
        </div>
      </header>

      <div className="activity-page__layout">
        <aside className="activity-page__sidebar">
          <div className="activity-page__all-events">
            <ActivityIcon name="all" />
            <span className="activity-page__all-events-label">All Events</span>
            <span className="activity-page__all-events-count">{events.length}</span>
          </div>

          <GlassCard title="Filter by Type">
            <div className="activity-page__filters" role="group" aria-label="Filters">
              {ACTIVITY_CATEGORIES.map((entry) => (
                <button
                  key={entry.id}
                  type="button"
                  aria-label={entry.label}
                  aria-pressed={category === entry.id}
                  className={
                    "activity-page__filter" + (category === entry.id ? " activity-page__filter--active" : "")
                  }
                  onClick={() => setCategory(entry.id)}
                >
                  <ActivityIcon
                    name={entry.id as ActivityIconName}
                    className={`activity-page__filter-icon activity-page__filter-icon--${
                      ACTIVITY_CATEGORY_TONE[entry.id] ?? "neutral"
                    }`}
                  />
                  <span className="activity-page__filter-label" aria-hidden="true">
                    {entry.label}
                  </span>
                  <span className="activity-page__filter-count" aria-hidden="true">
                    {categoryCounts.get(entry.id) ?? 0}
                  </span>
                </button>
              ))}
            </div>
          </GlassCard>

          <GlassCard title="Summary (Today)">
            <dl className="activity-page__summary">
              <div className="activity-page__summary-item">
                <dt>Tasks Completed</dt>
                <dd>{tasksCompleted}</dd>
              </div>
              <div className="activity-page__summary-item">
                <dt>Success Rate</dt>
                <dd>{successRate != null ? `${successRate.toFixed(0)}%` : "—"}</dd>
              </div>
              <div className="activity-page__summary-item">
                <dt>Total Actions</dt>
                <dd>{totalActions}</dd>
              </div>
              <div className="activity-page__summary-item">
                <dt>Replans</dt>
                <dd>{totalReplans}</dd>
              </div>
            </dl>
          </GlassCard>
        </aside>

        <section className="activity-page__feed-col">
          <GlassCard className="activity-page__feed-card">
            <div className="activity-page__feed-header">
              <span className="activity-page__feed-header-label">Today</span>
              <span className="activity-page__feed-header-date">
                <ActivityIcon name="calendar" />
                {headerDate}
              </span>
            </div>

            <section aria-label="Activity Feed" className="activity-page__feed">
              {status === "loading" && events.length === 0 && (
                <p className="activity-page__loading">Loading...</p>
              )}
              {status !== "loading" && filtered.length === 0 && (
                <div className="activity-page__empty">
                  <span className="activity-page__empty-ring" aria-hidden="true" />
                  <p>No activity yet.</p>
                  <p className="activity-page__empty-detail">MILO hasn't recorded any events.</p>
                </div>
              )}
              {filtered.length > 0 && (
                <ul className="activity-page__list">
                  {filtered.map((event) => {
                    const eventCategory = categorizeEvent(event);
                    return (
                      <li key={event.event_id} className="activity-page__list-item">
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
                          <span className="activity-page__item-node" aria-hidden="true" />
                          <span
                            className={
                              "activity-page__item-icon" +
                              (eventCategory
                                ? ` activity-page__item-icon--${ACTIVITY_CATEGORY_TONE[eventCategory.id] ?? "neutral"}`
                                : "")
                            }
                            aria-hidden="true"
                          >
                            <ActivityIcon name={(eventCategory?.id as ActivityIconName) ?? "all"} />
                          </span>
                          <span className="activity-page__item-body">
                            <span className="activity-page__item-event">{event.event}</span>
                            <span className="activity-page__item-agent">{event.agent}</span>
                          </span>
                          {eventCategory && (
                            <StatusPill
                              tone={ACTIVITY_CATEGORY_TONE[eventCategory.id] ?? "neutral"}
                              className="activity-page__item-badge"
                            >
                              {eventCategory.label}
                            </StatusPill>
                          )}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </section>
          </GlassCard>
        </section>

        <aside className="activity-page__details-col">
          <GlassCard title="Event Details" className="activity-page__details-card">
            <section aria-label="Event Details">
              {!selected && <p className="activity-page__details-empty">Select an event to see its details.</p>}
              {selected && (
                <>
                  <div className="activity-page__hero">
                    <span
                      className={
                        "activity-page__hero-icon" +
                        (selectedCategory
                          ? ` activity-page__hero-icon--${ACTIVITY_CATEGORY_TONE[selectedCategory.id] ?? "neutral"}`
                          : "")
                      }
                    >
                      <ActivityIcon name={(selectedCategory?.id as ActivityIconName) ?? "all"} />
                    </span>
                    <p className="activity-page__hero-title">{formatEventLabel(selected.event)}</p>
                    {selectedCategory && (
                      <StatusPill tone={ACTIVITY_CATEGORY_TONE[selectedCategory.id] ?? "neutral"}>
                        {selectedCategory.label}
                      </StatusPill>
                    )}
                  </div>

                  <div className="activity-page__metrics">
                    <div className="activity-page__metric">
                      <dt>Time</dt>
                      <dd>{formatTimestamp(selected.timestamp).time}</dd>
                    </div>
                    <div className="activity-page__metric">
                      <dt>Date</dt>
                      <dd>{formatTimestamp(selected.timestamp).date}</dd>
                    </div>
                    {selected.latency_ms != null && (
                      <div className="activity-page__metric">
                        <dt>Latency</dt>
                        <dd>{selected.latency_ms.toFixed(1)} ms</dd>
                      </div>
                    )}
                  </div>

                  <dl className="activity-page__detail-list">
                    <dt>Agent</dt>
                    <dd>{selected.agent}</dd>
                    <dt>Event</dt>
                    <dd>{selected.event}</dd>
                  </dl>

                  {selectedTask && (
                    <div className="activity-page__related">
                      <p className="activity-page__related-label">Related To</p>
                      <div className="activity-page__related-task">
                        <ActivityIcon name="task-link" />
                        <span>{selectedTask.user_request}</span>
                      </div>
                    </div>
                  )}

                  <div className="activity-page__metadata">
                    <p className="activity-page__metadata-label">Metadata</p>
                    <pre className="activity-page__payload">{JSON.stringify(selected.payload, null, 2)}</pre>
                  </div>
                </>
              )}
            </section>
          </GlassCard>
        </aside>
      </div>
    </main>
  );
}

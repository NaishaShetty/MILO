// ActivityPage.tsx
//
// Purpose
// -------
// "What has MILO been doing?" -- a merged, filterable, searchable feed
// of every real event from `GET /tasks/{id}/events` across the recent
// tasks in `TaskContext.history` (`useActivityEvents`). Filtering/
// search/export logic lives in `utils/activity.ts` (unit-tested there)
// so this component stays pure rendering + selection state.
import { useMemo, useState } from "react";

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

  return (
    <main aria-label="Activity" className="activity-page">
      <h1>Activity</h1>

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

      <div className="activity-page__filters" role="group" aria-label="Filters">
        {ACTIVITY_CATEGORIES.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className={
              "activity-page__filter" + (category === entry.id ? " activity-page__filter--active" : "")
            }
            onClick={() => setCategory(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </div>

      <div className="activity-page__body">
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

        <section aria-label="Event Details" className="activity-page__details">
          <h2>Event Details</h2>
          {!selected && <p>Select an event to see its details.</p>}
          {selected && (
            <dl>
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
                <pre className="activity-page__payload">{JSON.stringify(selected.payload, null, 2)}</pre>
              </dd>
            </dl>
          )}
        </section>
      </div>
    </main>
  );
}

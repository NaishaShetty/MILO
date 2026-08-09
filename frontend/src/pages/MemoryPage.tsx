// MemoryPage.tsx
//
// Purpose
// -------
// "What does MILO remember?" -- built entirely from real per-task
// memory data already returned by `GET /tasks` (each `TaskState`
// carries its own `retrieved_memories`/`created_memories`, see
// `backend/agents/task_state.py`), aggregated by `utils/memory.ts`.
// No generic memory-search endpoint exists on the backend (Session 3
// audit), so "Quick Memory Search" below asks a real question through
// the real task pipeline (`TaskContext.submitInstruction`, the same
// call `TalkToMilo` uses) rather than filtering local data -- the
// answer is whatever the real memory-retrieval agent actually
// retrieved for that question, not a fake client-side search.
import { useMemo, useState } from "react";
import type { FormEvent } from "react";

import { useTask } from "../state/TaskContext";
import {
  aggregateMemories,
  countsByType,
  MEMORY_CATEGORY_LABELS,
  semanticKnowledge,
} from "../utils/memory";

const CATEGORY_ORDER = ["semantic", "episodic", "failure", "user"];

export function MemoryPage() {
  const { history, historyStatus, submitInstruction, submitting, submitError, activeTask } = useTask();
  const [question, setQuestion] = useState("");
  const [askedTaskId, setAskedTaskId] = useState<string | null>(null);

  const entries = useMemo(() => aggregateMemories(history), [history]);
  const counts = useMemo(() => countsByType(entries), [entries]);
  const knowledge = useMemo(() => semanticKnowledge(entries), [entries]);

  const askedTask = askedTaskId && activeTask?.task_id === askedTaskId ? activeTask : null;

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || submitting) return;
    try {
      const state = await submitInstruction(trimmed, "text");
      setAskedTaskId(state.task_id);
    } catch {
      // `submitError` already carries a safe message for this form.
    }
  }

  return (
    <main aria-label="Memory" className="memory-page">
      <h1>🧠 Memory</h1>

      <section aria-label="Memory Categories" className="memory-page__section">
        <h2>Memory Categories</h2>
        <ul className="memory-page__categories">
          {CATEGORY_ORDER.map((type) => (
            <li key={type} className="memory-page__category">
              <span className="memory-page__category-label">{MEMORY_CATEGORY_LABELS[type]}</span>
              <span className="memory-page__category-count">{counts[type] ?? 0}</span>
            </li>
          ))}
        </ul>
      </section>

      <section aria-label="Quick Memory Search" className="memory-page__section">
        <h2>Quick Memory Search</h2>
        <form onSubmit={handleSearch} className="memory-page__search-form">
          <label htmlFor="memory-search-input" className="memory-page__search-label">
            Ask MILO about its memory
          </label>
          <div className="memory-page__search-row">
            <input
              id="memory-search-input"
              type="text"
              placeholder="Where did you last see the mug?"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              disabled={submitting}
            />
            <button type="submit" disabled={submitting || question.trim().length === 0}>
              {submitting ? "Asking..." : "Ask"}
            </button>
          </div>
        </form>
        {submitError && (
          <p className="memory-page__error" role="alert">
            {submitError}
          </p>
        )}
        {askedTask && (
          <div className="memory-page__search-result" aria-live="polite">
            <p>Status: {askedTask.status}</p>
            {askedTask.retrieved_memories.length === 0 ? (
              <p>No matching memories found.</p>
            ) : (
              <ul>
                {askedTask.retrieved_memories.map((memory, index) => (
                  <li key={memory.memory_id ?? index}>{memory.content ?? "One memory (no content field)."}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </section>

      <section aria-label="My Knowledge" className="memory-page__section">
        <h2>My Knowledge</h2>
        {knowledge.length === 0 ? (
          <p>No knowledge yet.</p>
        ) : (
          <ul className="memory-page__knowledge">
            {knowledge.map((entry, index) => (
              <li key={entry.memory_id ?? index}>{entry.content ?? "One semantic memory (no content field)."}</li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Recent Memories" className="memory-page__section">
        <h2>Recent Memories</h2>
        {historyStatus === "loading" && entries.length === 0 && <p>Loading...</p>}
        {historyStatus !== "loading" && entries.length === 0 && <p>No memories yet.</p>}
        {entries.length > 0 && (
          <ul className="memory-page__recent">
            {entries.slice(0, 20).map((entry, index) => (
              <li key={entry.memory_id ?? index} className="memory-page__recent-item">
                <span className="memory-page__recent-type">
                  {entry.memory_type ? MEMORY_CATEGORY_LABELS[entry.memory_type] ?? entry.memory_type : "Unknown"}
                </span>
                <span className="memory-page__recent-source">{entry.source}</span>
                <span className="memory-page__recent-content">
                  {entry.content ?? "(no content field)"}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Memory Timeline" className="memory-page__section">
        <h2>Memory Timeline</h2>
        {entries.length === 0 ? (
          <p>No memory activity yet.</p>
        ) : (
          <ol className="memory-page__timeline">
            {entries.map((entry, index) => (
              <li key={entry.memory_id ?? index}>
                Task {entry.task_id}: {entry.source} a {entry.memory_type ?? "unknown"} memory
              </li>
            ))}
          </ol>
        )}
      </section>

      <section aria-label="Memory Statistics" className="memory-page__section">
        <h2>Memory Statistics</h2>
        <ul className="memory-page__stats">
          <li>Semantic: {counts.semantic ?? 0}</li>
          <li>Episodic: {counts.episodic ?? 0}</li>
          <li>Failures: {counts.failure ?? 0}</li>
          <li>Preferences: {counts.user ?? 0}</li>
        </ul>
      </section>
    </main>
  );
}

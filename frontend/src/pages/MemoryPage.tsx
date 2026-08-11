// MemoryPage.tsx
//
// Purpose
// -------
// "What does MILO remember?" -- wired to the real Memory API
// (`GET /api/v1/memory`, `GET /api/v1/memory/search`,
// `backend/api/routes/memory.py`): "Quick Memory Search" asks the real
// MemoryAgent directly (no throwaway task creation), and every
// category count/listing/timeline entry comes from the real
// persistent memory store (`useMemoryList`) -- every memory MILO has
// ever stored, not just ones this browser session happened to poll
// into task history.
//
// Visual refinement pass: header (title + real search) / three-column
// body (Memory Types filters+summary | Memory Feed | Memory Details)
// / a de-emphasized real Memory Timeline / a static "How MILO
// Remembers" explanatory diagram (no live data, see its own comment).
// The category filter tabs now actually filter the feed (client-side,
// over the same already-loaded `memories` array -- no new fetch) and
// selecting a card populates the new Memory Details panel from that
// same real `Memory` object; every other string a test asserts on
// ("Things I Know"/"Experiences"/"Things That Went Wrong"/"Your
// Preferences", "No memories yet.", "Semantic: 1", "Failures: 1", the
// "My Knowledge" region, "Ask MILO about its memory", the "<provenance>
// created a <type> memory" timeline sentence) is unchanged.
import { useMemo, useState } from "react";
import type { FormEvent } from "react";

import { GlassCard } from "../components/GlassCard";
import { MemoryIcon, MEMORY_CATEGORY_TONE } from "../components/MemoryIcons";
import type { MemoryIconName } from "../components/MemoryIcons";
import { MiloAvatar } from "../components/MiloAvatar";
import { StatusPill } from "../components/StatusPill";
import { searchMemory } from "../api/memory";
import type { Memory, MemorySearchResult } from "../api/memoryTypes";
import { useMemoryList } from "../hooks/useMemoryList";
import { useMiloState } from "../state/MiloStateContext";
import { useTask } from "../state/TaskContext";
import { MEMORY_CATEGORY_LABELS } from "../utils/memory";

const CATEGORY_ORDER = ["semantic", "episodic", "failure", "user"];
const FILTER_TABS = [{ id: "all", label: "All" }, ...CATEGORY_ORDER.map((id) => ({ id, label: MEMORY_CATEGORY_LABELS[id] }))];

type SearchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; query: string; results: MemorySearchResult[] }
  | { status: "error"; message: string };

function formatTimestamp(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toLocaleString();
}

export function MemoryPage() {
  const { memories, countsByType, status: listStatus, refresh } = useMemoryList();
  const { history } = useTask();
  const miloState = useMiloState();
  const [question, setQuestion] = useState("");
  const [activeCategory, setActiveCategory] = useState<string>("all");
  const [search, setSearch] = useState<SearchState>({ status: "idle" });
  const [selected, setSelected] = useState<Memory | null>(null);

  const knowledge = useMemo(
    () => memories.filter((entry) => entry.memory_type === "semantic"),
    [memories],
  );

  const filteredMemories = useMemo(
    () => (activeCategory === "all" ? memories : memories.filter((m) => m.memory_type === activeCategory)),
    [memories, activeCategory],
  );

  const totalMemories = memories.length;
  const selectedTask = selected?.task_id ? history.find((t) => t.task_id === selected.task_id) ?? null : null;

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || search.status === "loading") return;
    setSearch({ status: "loading" });
    try {
      const response = await searchMemory(trimmed);
      setSearch({ status: "success", query: response.query, results: response.results });
    } catch (error) {
      setSearch({
        status: "error",
        message: error instanceof Error ? error.message : "Memory search failed.",
      });
    }
  }

  function selectFromSearch(result: MemorySearchResult) {
    setSelected(result.memory);
  }

  return (
    <main aria-label="Memory" className="memory-page">
      <h1 className="sr-only">Memory</h1>

      <header className="memory-page__header">
        <div className="memory-page__header-copy">
          <div className="memory-page__hero-character" aria-hidden="true">
            <MiloAvatar state={miloState} size="sm" />
          </div>
          <div>
            <p className="memory-page__title">
              Memory <span className="memory-page__title-dot" aria-hidden="true" />
            </p>
            <p className="memory-page__subtitle">What MILO remembers, learns, and retrieves.</p>
          </div>
        </div>

        <GlassCard className="memory-page__search-card">
          <section aria-label="Quick Memory Search">
            <form onSubmit={handleSearch} className="memory-page__search-form">
              <label htmlFor="memory-search-input" className="memory-page__search-label">
                Ask MILO about its memory
              </label>
              <div className="memory-page__search-row">
                <div className="memory-page__search-input-wrap">
                  <input
                    id="memory-search-input"
                    type="text"
                    placeholder="Search memories..."
                    value={question}
                    onChange={(event) => setQuestion(event.target.value)}
                    disabled={search.status === "loading"}
                  />
                  <MemoryIcon name="search" className="memory-page__search-icon" />
                </div>
                <button
                  type="submit"
                  className="memory-page__search-submit"
                  disabled={search.status === "loading" || question.trim().length === 0}
                >
                  {search.status === "loading" ? "Asking..." : "Ask"}
                </button>
              </div>
            </form>
            {search.status === "error" && (
              <p className="memory-page__error" role="alert">
                {search.message}
              </p>
            )}
          </section>
        </GlassCard>
      </header>

      <div className="memory-page__body">
        <aside className="memory-page__sidebar">
          <GlassCard title="Memory Types">
            <div className="memory-page__categories" role="tablist" aria-label="Memory Categories">
              {FILTER_TABS.map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  role="tab"
                  aria-selected={activeCategory === tab.id}
                  className={
                    "memory-page__category" + (activeCategory === tab.id ? " memory-page__category--active" : "")
                  }
                  onClick={() => setActiveCategory(tab.id)}
                >
                  <MemoryIcon
                    name={tab.id as MemoryIconName}
                    className={`memory-page__category-icon memory-page__category-icon--${
                      MEMORY_CATEGORY_TONE[tab.id] ?? "neutral"
                    }`}
                  />
                  <span className="memory-page__category-label">{tab.label}</span>
                  <span className="memory-page__category-count">
                    {tab.id === "all" ? totalMemories : countsByType[tab.id] ?? 0}
                  </span>
                </button>
              ))}
            </div>
          </GlassCard>

          <GlassCard title="My Knowledge" className="memory-page__knowledge-card">
            <section aria-label="My Knowledge">
              {knowledge.length === 0 ? (
                <p className="memory-page__empty-inline">No knowledge yet.</p>
              ) : (
                <ul className="memory-page__knowledge">
                  {knowledge.slice(0, 6).map((entry) => (
                    <li key={entry.memory_id}>{entry.content}</li>
                  ))}
                </ul>
              )}
            </section>
          </GlassCard>

          <GlassCard title="Summary">
            <section aria-label="Memory Statistics" className="memory-page__summary">
              <div className="memory-page__stat-grid">
                <div className="memory-page__stat">
                  <span className="memory-page__stat-label">Semantic</span>
                  <span className="memory-page__stat-value">{countsByType.semantic ?? 0}</span>
                  <span className="sr-only">Semantic: {countsByType.semantic ?? 0}</span>
                </div>
                <div className="memory-page__stat">
                  <span className="memory-page__stat-label">Episodic</span>
                  <span className="memory-page__stat-value">{countsByType.episodic ?? 0}</span>
                  <span className="sr-only">Episodic: {countsByType.episodic ?? 0}</span>
                </div>
                <div className="memory-page__stat">
                  <span className="memory-page__stat-label">Failure</span>
                  <span className="memory-page__stat-value">{countsByType.failure ?? 0}</span>
                  <span className="sr-only">Failures: {countsByType.failure ?? 0}</span>
                </div>
                <div className="memory-page__stat">
                  <span className="memory-page__stat-label">User</span>
                  <span className="memory-page__stat-value">{countsByType.user ?? 0}</span>
                  <span className="sr-only">Preferences: {countsByType.user ?? 0}</span>
                </div>
              </div>
              <p className="memory-page__total">{totalMemories} memories total.</p>
            </section>
          </GlassCard>
        </aside>

        <section className="memory-page__feed-col">
          <GlassCard
            title={search.status === "success" ? "Search Results" : "Memory Feed"}
            titleAction={
              <button
                type="button"
                className="memory-page__refresh"
                onClick={() => refresh()}
                aria-label="Refresh memories"
                title="Refresh memories"
              >
                <MemoryIcon name="refresh" />
              </button>
            }
            className="memory-page__feed-card"
          >
            <section aria-label="Recent Memories">
              {search.status === "success" ? (
                <>
                  <p className="memory-page__search-query">&ldquo;{search.query}&rdquo;</p>
                  {search.results.length === 0 ? (
                    <p className="memory-page__empty-inline">No memories match your search.</p>
                  ) : (
                    <ul className="memory-page__feed" aria-live="polite">
                      {search.results.map((result) => (
                        <li key={result.memory.memory_id}>
                          <button
                            type="button"
                            className={
                              "memory-page__card" +
                              (selected?.memory_id === result.memory.memory_id ? " memory-page__card--selected" : "")
                            }
                            onClick={() => selectFromSearch(result)}
                          >
                            <span className="memory-page__card-header">
                              <span
                                className={`memory-page__card-icon memory-page__card-icon--${
                                  MEMORY_CATEGORY_TONE[result.memory.memory_type] ?? "neutral"
                                }`}
                              >
                                <MemoryIcon name={result.memory.memory_type as MemoryIconName} />
                              </span>
                              <span className="memory-page__card-type">
                                {MEMORY_CATEGORY_LABELS[result.memory.memory_type] ?? result.memory.memory_type}
                              </span>
                              <StatusPill tone="info" className="memory-page__search-score">
                                {Math.round(result.final_score * 100)}% match
                              </StatusPill>
                            </span>
                            <p className="memory-page__card-content">{result.memory.content}</p>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              ) : (
                <>
                  {listStatus === "loading" && memories.length === 0 && (
                    <p className="memory-page__empty-inline">Loading...</p>
                  )}
                  {listStatus !== "loading" && memories.length === 0 && (
                    <div className="memory-page__empty">
                      <span className="memory-page__empty-ring" aria-hidden="true" />
                      <p>No memories yet.</p>
                      <p className="memory-page__empty-detail">
                        MILO will build memory as it perceives, acts, and learns from experience.
                      </p>
                    </div>
                  )}
                  {listStatus !== "loading" && memories.length > 0 && filteredMemories.length === 0 && (
                    <p className="memory-page__empty-inline">No {activeCategory} memories yet.</p>
                  )}
                  {filteredMemories.length > 0 && (
                    <ul className="memory-page__feed">
                      {filteredMemories.slice(0, 30).map((entry) => (
                        <li key={entry.memory_id}>
                          <button
                            type="button"
                            className={
                              "memory-page__card" +
                              (selected?.memory_id === entry.memory_id ? " memory-page__card--selected" : "") +
                              (entry.memory_type === "failure" ? " memory-page__card--failure" : "")
                            }
                            onClick={() => setSelected(entry)}
                          >
                            <span className="memory-page__card-header">
                              <span
                                className={`memory-page__card-icon memory-page__card-icon--${
                                  MEMORY_CATEGORY_TONE[entry.memory_type] ?? "neutral"
                                }`}
                              >
                                <MemoryIcon name={entry.memory_type as MemoryIconName} />
                              </span>
                              <span className="memory-page__card-type">
                                {MEMORY_CATEGORY_LABELS[entry.memory_type] ?? entry.memory_type}
                              </span>
                              <span className="memory-page__card-time">{formatTimestamp(entry.created_at)}</span>
                            </span>
                            <p className="memory-page__card-content">{entry.content}</p>
                            <span className="memory-page__card-meta">
                              <span className="memory-page__card-meta-item">Source: {entry.provenance}</span>
                              <span className="memory-page__card-meta-item">
                                Confidence: {entry.confidence.toFixed(2)}
                              </span>
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
            </section>
          </GlassCard>
        </section>

        <aside className="memory-page__details-col">
          <GlassCard title="Memory Details" className="memory-page__details-card">
            <section aria-label="Memory Details">
              {!selected && (
                <p className="memory-page__empty-inline">Select a memory to inspect its details.</p>
              )}
              {selected && (
                <>
                  <div className="memory-page__detail-hero">
                    <span
                      className={`memory-page__detail-icon memory-page__detail-icon--${
                        MEMORY_CATEGORY_TONE[selected.memory_type] ?? "neutral"
                      }`}
                    >
                      <MemoryIcon name={selected.memory_type as MemoryIconName} />
                    </span>
                    <p className="memory-page__detail-content">{selected.content}</p>
                  </div>

                  <dl className="memory-page__detail-list">
                    <dt>Type</dt>
                    <dd>{MEMORY_CATEGORY_LABELS[selected.memory_type] ?? selected.memory_type}</dd>
                    <dt>Created</dt>
                    <dd>{formatTimestamp(selected.created_at)}</dd>
                    <dt>Source</dt>
                    <dd>{selected.provenance}</dd>
                    <dt>Confidence</dt>
                    <dd>{selected.confidence.toFixed(2)}</dd>
                  </dl>

                  {selected.task_id && (
                    <div className="memory-page__detail-related">
                      <p className="memory-page__detail-related-label">Related Task</p>
                      <div className="memory-page__detail-related-task">
                        <MemoryIcon name="task" />
                        <span>{selectedTask ? selectedTask.user_request : selected.task_id}</span>
                      </div>
                    </div>
                  )}

                  {Object.keys(selected.metadata).length > 0 && (
                    <div className="memory-page__detail-metadata">
                      <p className="memory-page__detail-related-label">Metadata</p>
                      <pre className="memory-page__payload">{JSON.stringify(selected.metadata, null, 2)}</pre>
                    </div>
                  )}
                </>
              )}
            </section>
          </GlassCard>
        </aside>
      </div>

      <GlassCard title="Memory Timeline" className="memory-page__timeline-card">
        <section aria-label="Memory Timeline">
          {memories.length === 0 ? (
            <p className="memory-page__empty-inline">No memory activity yet.</p>
          ) : (
            <ol className="memory-page__timeline">
              {memories.slice(0, 12).map((entry) => (
                <li key={entry.memory_id}>
                  <span className="memory-page__timeline-time">{formatTimestamp(entry.created_at)}</span>
                  <span>
                    {entry.provenance} created a {entry.memory_type} memory
                  </span>
                </li>
              ))}
            </ol>
          )}
        </section>
      </GlassCard>

      {/* Static explanatory diagram, not a live pipeline -- no per-stage
       * data exists to show real-time here, so this is only ever a
       * fixed description of the real memory lifecycle (see
       * backend/memory/agent.py's perceive -> reflect -> store -> retrieve
       * flow), never an animated/fabricated "memory being created now". */}
      <section className="memory-page__pipeline" aria-label="How MILO Remembers">
        <p className="memory-page__pipeline-title">How MILO Remembers</p>
        <div className="memory-page__pipeline-steps">
          <span>Perceive</span>
          <MemoryIcon name="chevron" />
          <span>Experience</span>
          <MemoryIcon name="chevron" />
          <span>Reflect</span>
          <MemoryIcon name="chevron" />
          <span>Remember</span>
          <MemoryIcon name="chevron" />
          <span>Retrieve</span>
        </div>
      </section>
    </main>
  );
}

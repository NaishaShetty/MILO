// MemoryPage.tsx
//
// Purpose
// -------
// "What does MILO remember?" -- Phase 8.2 wires this to the real
// Memory API (`GET /api/v1/memory`, `GET /api/v1/memory/search`,
// `backend/api/routes/memory.py`) instead of the earlier fake-task
// workaround: "Quick Memory Search" now asks the real MemoryAgent
// directly (no throwaway task creation), and every category count/
// listing/timeline entry comes from the real persistent memory store
// (`useMemoryList`) -- every memory MILO has ever stored, not just
// ones this browser session happened to poll into task history.
import { useMemo, useState } from "react";
import type { FormEvent } from "react";

import { GlassCard } from "../components/GlassCard";
import { StatusPill } from "../components/StatusPill";
import { searchMemory } from "../api/memory";
import type { MemorySearchResult } from "../api/memoryTypes";
import { useMemoryList } from "../hooks/useMemoryList";
import { MEMORY_CATEGORY_LABELS } from "../utils/memory";

const CATEGORY_ORDER = ["semantic", "episodic", "failure", "user"];

type SearchState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; query: string; results: MemorySearchResult[] }
  | { status: "error"; message: string };

function formatTimestamp(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toLocaleString();
}

export function MemoryPage() {
  const { memories, countsByType, status: listStatus } = useMemoryList();
  const [question, setQuestion] = useState("");
  const [search, setSearch] = useState<SearchState>({ status: "idle" });

  const knowledge = useMemo(
    () => memories.filter((entry) => entry.memory_type === "semantic"),
    [memories],
  );

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

  return (
    <main aria-label="Memory" className="memory-page">
      <h1>Memory</h1>

      <GlassCard title="Memory Categories" className="memory-page__section">
        <section aria-label="Memory Categories">
          <ul className="memory-page__categories">
            {CATEGORY_ORDER.map((type) => (
              <li key={type} className="memory-page__category">
                <span className="memory-page__category-label">{MEMORY_CATEGORY_LABELS[type]}</span>
                <span className="memory-page__category-count">{countsByType[type] ?? 0}</span>
              </li>
            ))}
          </ul>
        </section>
      </GlassCard>

      <GlassCard title="Quick Memory Search" className="memory-page__section">
        <section aria-label="Quick Memory Search">
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
                disabled={search.status === "loading"}
              />
              <button
                type="submit"
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
          {search.status === "success" && (
            <div className="memory-page__search-result" aria-live="polite">
              {search.results.length === 0 ? (
                <p>No matching memories found.</p>
              ) : (
                <ul>
                  {search.results.map((result) => (
                    <li key={result.memory.memory_id}>
                      {result.memory.content}
                      <StatusPill tone="info" className="memory-page__search-score">
                        {Math.round(result.final_score * 100)}% match
                      </StatusPill>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>
      </GlassCard>

      <GlassCard title="My Knowledge" className="memory-page__section">
        <section aria-label="My Knowledge">
          {knowledge.length === 0 ? (
            <p>No knowledge yet.</p>
          ) : (
            <ul className="memory-page__knowledge">
              {knowledge.map((entry) => (
                <li key={entry.memory_id}>{entry.content}</li>
              ))}
            </ul>
          )}
        </section>
      </GlassCard>

      <GlassCard title="Recent Memories" className="memory-page__section">
        <section aria-label="Recent Memories">
          {listStatus === "loading" && memories.length === 0 && <p>Loading...</p>}
          {listStatus !== "loading" && memories.length === 0 && <p>No memories yet.</p>}
          {memories.length > 0 && (
            <ul className="memory-page__recent">
              {memories.slice(0, 20).map((entry) => (
                <li key={entry.memory_id} className="memory-page__recent-item">
                  <span className="memory-page__recent-type">
                    {MEMORY_CATEGORY_LABELS[entry.memory_type] ?? entry.memory_type}
                  </span>
                  <span className="memory-page__recent-source">{entry.provenance}</span>
                  <span className="memory-page__recent-content">{entry.content}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </GlassCard>

      <GlassCard title="Memory Timeline" className="memory-page__section">
        <section aria-label="Memory Timeline">
          {memories.length === 0 ? (
            <p>No memory activity yet.</p>
          ) : (
            <ol className="memory-page__timeline">
              {memories.map((entry) => (
                <li key={entry.memory_id}>
                  {formatTimestamp(entry.created_at)}: {entry.provenance} created a{" "}
                  {entry.memory_type} memory
                </li>
              ))}
            </ol>
          )}
        </section>
      </GlassCard>

      <GlassCard title="Memory Statistics" className="memory-page__section">
        <section aria-label="Memory Statistics">
          <ul className="memory-page__stats">
            <li>Semantic: {countsByType.semantic ?? 0}</li>
            <li>Episodic: {countsByType.episodic ?? 0}</li>
            <li>Failures: {countsByType.failure ?? 0}</li>
            <li>Preferences: {countsByType.user ?? 0}</li>
          </ul>
        </section>
      </GlassCard>
    </main>
  );
}

// MemoryPage.tsx -- "MILO's scrapbook": search, filters, Fact / Moment / Oops
// cards, a legend, and a "Forget this" button on every card.
import { useState } from "react";

import { deleteMemory, editMemory, forgetMemory } from "../api/memory";
import type { Memory, MemoryTrust } from "../api/memoryTypes";
import { MiloRobot } from "../components/MiloRobot";
import { useMemoryList } from "../hooks/useMemoryList";
import { relativeDay, sureness } from "../utils/friendly";

type Filter = "all" | "moment" | "fact" | "oops";
const FILTERS: Array<{ id: Filter; label: string }> = [
  { id: "all", label: "All" },
  { id: "moment", label: "Moments" },
  { id: "fact", label: "Facts" },
  { id: "oops", label: "Oops" },
];

function kindOf(memory: Memory): Exclude<Filter, "all"> {
  if (memory.memory_type === "failure") return "oops";
  if (memory.memory_type === "episodic") return "moment";
  return "fact";
}

const SOURCE_LABEL: Record<MemoryTrust["source"], string> = {
  user: "you told me",
  observation: "I saw it",
  skill: "I worked it out",
  imported: "imported",
};

type Act = (fn: () => Promise<unknown>) => void;

function Card({ memory, trust, onForget, act }: { memory: Memory; trust?: MemoryTrust; onForget: (m: Memory) => void; act: Act }) {
  const kind = kindOf(memory);
  const [fixing, setFixing] = useState(false);
  const [place, setPlace] = useState("");
  const meta = memory.metadata as Record<string, unknown>;
  const sure = sureness(memory.confidence);
  const label = { fact: "Fact", moment: "Moment", oops: "Oops" }[kind];
  return (
    <article className={`scrap scrap--${kind}`}>
      <div className="scrap__top">
        <span className="pill">{label}</span>
        {trust && <span className="tag">{SOURCE_LABEL[trust.source]}</span>}
        {trust?.pinned && <span className="tag">pinned</span>}
        {trust?.quarantined && <span className="tag">set aside</span>}
        <span className="muted">{relativeDay(memory.created_at)}</span>
      </div>
      {trust?.quarantined && (
        <p className="notice" role="note">
          I'm not using this because {trust.quarantine_reason ?? "it looked suspicious"}.
        </p>
      )}
      {kind === "fact" && typeof meta.subject === "string" ? (
        <div>
          <span className="tag">{String(meta.subject).replace(/_/g, " ")}</span>{" "}
          <span className="muted">{String(meta.predicate ?? "is").replace(/_/g, " ")}</span>{" "}
          <span className="tag">{String(meta.object ?? "").replace(/_/g, " ")}</span>
        </div>
      ) : (
        <h3>{memory.content}</h3>
      )}
      {kind === "fact" && (
        <span className="muted" title={`${Math.round(memory.confidence * 100)}% sure`}>
          {sure.label} {"●".repeat(sure.dots)}
          {"○".repeat(5 - sure.dots)}
        </span>
      )}
      {kind === "oops" && <span className="muted">Learned: this kind of thing can go wrong, so MILO is more careful.</span>}
      {fixing && (
        <span className="ask__row">
          <input className="input" aria-label="Correct place" value={place} placeholder="the right place" onChange={(e) => setPlace(e.target.value)} />
          <button type="button" className="btn btn--go" onClick={() => { act(() => editMemory(memory.memory_id, { place })); setFixing(false); }}>
            Save
          </button>
        </span>
      )}
      <div className="filters">
        {kind === "fact" && typeof meta.subject === "string" && !fixing && (
          <button type="button" className="filter" onClick={() => setFixing(true)}>
            Fix the place
          </button>
        )}
        <button type="button" className="filter" onClick={() => act(() => editMemory(memory.memory_id, { pinned: !trust?.pinned }))}>
          {trust?.pinned ? "Unpin" : "Pin"}
        </button>
        <button
          type="button"
          className="filter"
          onClick={() => act(() => editMemory(memory.memory_id, { quarantined: !trust?.quarantined }))}
        >
          {trust?.quarantined ? "Use it again" : "Set aside"}
        </button>
        <button type="button" className="btn" onClick={() => onForget(memory)} aria-label={`Forget this: ${memory.content}`}>
          Forget this
        </button>
        <button
          type="button"
          className="filter"
          onClick={() => {
            if (window.confirm("Delete this memory for good? This can't be undone.")) act(() => deleteMemory(memory.memory_id));
          }}
        >
          Delete
        </button>
      </div>
    </article>
  );
}

export function MemoryPage() {
  const { memories, status, error, refresh, trust, quarantined } = useMemoryList();
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  async function forget(memory: Memory) {
    try {
      await forgetMemory(memory.memory_id);
      setProblem(null);
      refresh();
    } catch {
      setProblem("I couldn't forget that one. Please try again in a moment.");
    }
  }

  const act: Act = (fn) => {
    fn()
      .then(() => {
        setProblem(null);
        refresh();
      })
      .catch(() => setProblem("That didn't work. Please try again in a moment."));
  };

  const q = query.trim().toLowerCase();
  const shown = memories
    .filter((m) => m.status !== "archived")
    .filter((m) => filter === "all" || kindOf(m) === filter)
    .filter((m) => !q || `${m.content} ${JSON.stringify(m.metadata)}`.toLowerCase().includes(q));

  return (
    <div>
      <div className="mission-head">
        <div>
          <h1 className="scrapbook-title">
            MILO's <em>scrapbook</em>
          </h1>
          <p className="muted">Everything MILO remembers from past missions. The more it remembers, the fewer steps it wastes.</p>
        </div>
        <MiloRobot pose="speaking" size={110} />
      </div>
      <div className="filters">
        <input
          className="input"
          type="search"
          aria-label="Search memories"
          placeholder="Search an object or a place..."
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          style={{ maxWidth: 320 }}
        />
        {FILTERS.map((f) => (
          <button key={f.id} type="button" className="filter" aria-pressed={filter === f.id} onClick={() => setFilter(f.id)}>
            {f.label}
          </button>
        ))}
      </div>
      {problem && <div className="notice notice--error" role="alert">{problem}</div>}
      {quarantined > 0 && (
        <div className="notice" role="status">
          I've set aside {quarantined} {quarantined === 1 ? "memory" : "memories"} that looked wrong or suspicious. Look for "set aside"
          below: use them again or delete them.
        </div>
      )}
      <div className="memory-layout">
        <div>
          {status === "loading" && <div className="card empty">Flipping through the scrapbook...</div>}
          {status === "error" && (
            <div className="notice notice--error" role="alert">
              I couldn't open the scrapbook{error instanceof Error ? ` (${error.message})` : ""}. Check that MILO's server is running, then try again.
              <p><button type="button" className="btn" onClick={refresh}>Try again</button></p>
            </div>
          )}
          {status === "success" && shown.length === 0 && (
            <div className="card empty">
              {memories.length === 0 ? "Nothing here yet. MILO writes a page after every mission." : "No pages match. Try a different word or filter."}
            </div>
          )}
          <div className="scrap-grid">
            {shown.map((memory) => (
              <Card key={memory.memory_id} memory={memory} trust={trust[memory.memory_id]} onForget={forget} act={act} />
            ))}
          </div>
        </div>
        <aside className="legend card" aria-label="Three kinds of memory">
          <h2>Three kinds of memory</h2>
          <div className="legend__item" style={{ background: "var(--peach)" }}><strong>Moments</strong><span className="muted">What happened in a mission</span></div>
          <div className="legend__item" style={{ background: "var(--apricot)" }}><strong>Facts</strong><span className="muted">Where things usually are</span></div>
          <div className="legend__item" style={{ background: "var(--coral)" }}><strong>Oops notes</strong><span className="muted">What went wrong and what helped</span></div>
          <div className="notice">
            <strong>Tidy up</strong>
            <p>Old or wrong memories can be forgotten so MILO stops using them. Press "Forget this" on any card.</p>
          </div>
        </aside>
      </div>
    </div>
  );
}

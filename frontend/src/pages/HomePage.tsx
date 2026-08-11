// HomePage.tsx
//
// Purpose
// -------
// "Who is MILO?" / "Can I talk to MILO?" -- spec's Home page. Composes
// `TalkToMilo` (shared with Mission Control) for the text/speech input
// and quick examples, `AgentStatusList` (shared with Mission Control/
// Lab) for "MILO At a Glance," `PlanTimeline` (shared with Mission
// Control) for the Recent Mission progress row, and `useMemoryList`
// (shared with the Memory page) for a real multi-row "Latest Memory"
// list -- every value here is real data or an explicit empty state,
// never a fabricated number (spec Part 12/13).
//
// Visual pass: reproduces the Home mockup's cinematic three-zone hero
// (copy / robot+atmosphere / example card), command console, three
// dashboard cards, and bottom "try saying something" strip. The page's
// `<h1>` stays in the DOM (App-level routing test asserts one h1 per
// route matching its nav label) but is visually hidden -- the mockup's
// real hero heading is "Hi, I'm MILO", not a "HOME" eyebrow.
import { useMemo } from "react";

import { AgentStatusList } from "../components/AgentStatusList";
import { GlassCard } from "../components/GlassCard";
import { HomeIcon } from "../components/HomeIcons";
import type { HomeIconName } from "../components/HomeIcons";
import { MemoryIcon } from "../components/MemoryIcons";
import type { MemoryIconName } from "../components/MemoryIcons";
import { MiloAvatar } from "../components/MiloAvatar";
import { MiloStateIndicator } from "../components/MiloStateIndicator";
import { PlanTimeline } from "../components/PlanTimeline";
import { StatusPill } from "../components/StatusPill";
import { TalkToMilo } from "../components/TalkToMilo";
import { useAgents } from "../state/AgentsContext";
import { useMiloState } from "../state/MiloStateContext";
import { useTask } from "../state/TaskContext";
import { useMemoryList } from "../hooks/useMemoryList";
import type { Memory } from "../api/memoryTypes";

const QUICK_EXAMPLES = [
  "Find the apple",
  "Bring me the red mug",
  "Put the bottle on the table",
  "Where did you see the mug last time?",
];

// Illustrative only -- rendered as static copy in the hero's "you can
// ask me things like" panel, never as a submit action (the real
// submit affordances are TalkToMilo's input and its example buttons
// below). Kept distinct in wording from QUICK_EXAMPLES so this panel
// reads as "for instance" rather than duplicating actionable pills.
const ASK_ME_EXAMPLES: Array<{ text: string; icon: HomeIconName }> = [
  { text: "Bring me the red mug.", icon: "mug" },
  { text: "Where did you see the apple?", icon: "apple" },
  { text: "Put the bottle on the table.", icon: "bottle" },
];

// A per-string icon for the fixed QUICK_EXAMPLES copy above -- decorative
// only, keyed off the example's own fixed wording, not derived from any
// backend data.
const EXAMPLE_ICON: Record<string, HomeIconName> = {
  "Find the apple": "apple",
  "Bring me the red mug": "mug",
  "Put the bottle on the table": "bottle",
  "Where did you see the mug last time?": "question",
};

const GLANCE_AGENTS = ["vision", "memory", "planner", "navigation", "execution"];

function memoryText(entry: Memory): string {
  return typeof entry.content === "string" ? entry.content : "One new memory.";
}

function formatMemoryAge(unixSeconds: number): string {
  const deltaMs = Date.now() - unixSeconds * 1000;
  const minutes = Math.round(deltaMs / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function HomePage() {
  const { history, historyStatus } = useTask();
  const { agents, status: agentsStatus } = useAgents();
  const { memories } = useMemoryList();
  const miloState = useMiloState();
  const recentMission = history[0] ?? null;
  const recentMemories = useMemo(() => memories.slice(0, 4), [memories]);

  // Real, not invented: "all operational" only when every agent this
  // process has actually registered reports a non-error state -- an
  // empty registry (no simulator yet) is reported honestly, never as
  // "operational".
  const hasErrorAgent = agents.some((agent) => agent.state === "error");
  const systemsSummary =
    agentsStatus === "error"
      ? "Agent status unavailable"
      : agents.length === 0
        ? "No agents registered yet"
        : hasErrorAgent
          ? "Attention needed"
          : "All systems operational";
  // A dedicated tone per branch -- "unavailable"/"attention needed"
  // must never render as the same green "success" dot as "all systems
  // operational" (a real bug: `agentsStatus === "error"` used to fall
  // through to `hasErrorAgent`, which is false when `agents` is empty
  // on fetch failure, showing a false-positive green dot).
  const systemsTone =
    agentsStatus === "error" || hasErrorAgent
      ? "danger"
      : agents.length === 0
        ? "neutral"
        : "success";

  return (
    <main aria-label="Home" className="home-page">
      <h1 className="sr-only">Home</h1>

      <section className="home-page__hero milo-hero-panel">
        <div className="home-page__hero-atmosphere" aria-hidden="true">
          <span className="home-page__particle home-page__particle--1" />
          <span className="home-page__particle home-page__particle--2" />
          <span className="home-page__particle home-page__particle--3" />
          <span className="home-page__particle home-page__particle--4" />
        </div>

        <div className="home-page__intro">
          <p className="home-page__greeting-eyebrow">Hi, I'm</p>
          <p className="home-page__greeting">MILO</p>
          <p className="home-page__fullname">Memory Integrated Language Oriented Robot</p>
          <p className="home-page__description">
            I see the world, understand what you say, remember what I learn, and figure out the
            best way to help.
          </p>
          <div className="home-page__cta-row">
            <a href="#talk-to-milo-input" className="home-page__cta home-page__cta--primary">
              Talk to MILO <span aria-hidden="true">→</span>
            </a>
            <a href="/mission-control" className="home-page__cta home-page__cta--secondary">
              Watch Me in Action <span aria-hidden="true">▶</span>
            </a>
          </div>
        </div>

        <div className="home-page__character">
          <div className="milo-glow-orb" aria-hidden="true" />
          <MiloAvatar state={miloState} size="lg" className="home-page__avatar" />
          <div className="home-page__floor-rings" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
        </div>

        <aside className="home-page__ask-panel" aria-label="Example things you can ask MILO">
          <span className="home-page__ask-panel-pointer" aria-hidden="true" />
          <p className="home-page__ask-panel-title">You can ask me things like:</p>
          <ul className="home-page__ask-panel-list">
            {ASK_ME_EXAMPLES.map((example) => (
              <li key={example.text}>
                <HomeIcon name={example.icon} />
                &ldquo;{example.text}&rdquo;
              </li>
            ))}
          </ul>
          <a href="/about" className="home-page__ask-panel-more">
            See more examples <span aria-hidden="true">→</span>
          </a>
        </aside>
      </section>

      <TalkToMilo
        quickExamples={QUICK_EXAMPLES}
        prompt="What would you like me to do?"
        examplesLabel="Try an example:"
        examplesVariant="pills"
        layout="compact"
      />

      <div className="home-page__grid">
        <GlassCard title="MILO At a Glance" className="home-page__glance">
          <section aria-label="MILO At a Glance" className="home-page__glance-body">
            <div className="home-page__glance-status">
              <StatusPill tone={systemsTone} dot>
                {systemsSummary}
              </StatusPill>
              <AgentStatusList names={GLANCE_AGENTS} />
            </div>
            <div className="home-page__glance-divider" aria-hidden="true" />
            <div className="home-page__glance-milo">
              <MiloAvatar state={miloState} size="sm" />
              <MiloStateIndicator state={miloState} />
            </div>
          </section>
        </GlassCard>

        <GlassCard
          title="Recent Mission"
          titleAction={
            <a href="/mission-control" className="home-page__view-all">
              View All <span aria-hidden="true">→</span>
            </a>
          }
          className="home-page__recent-mission"
        >
          <section aria-label="Recent Mission">
            {historyStatus === "loading" && !recentMission && <p>Loading...</p>}
            {historyStatus !== "loading" && !recentMission && <p>No missions yet.</p>}
            {recentMission && (
              <div className="home-page__mission-card">
                <p className="home-page__mission-request">{recentMission.user_request}</p>
                <p className="home-page__mission-status">Status: {recentMission.status}</p>
                {recentMission.metrics.total_ms != null && (
                  <p className="home-page__mission-elapsed">
                    Took{" "}
                    {recentMission.metrics.total_ms / 1000 < 60
                      ? `${(recentMission.metrics.total_ms / 1000).toFixed(1)}s`
                      : `${(recentMission.metrics.total_ms / 60000).toFixed(1)}m`}
                  </p>
                )}
                {recentMission.current_plan && (
                  <div className="home-page__mission-timeline">
                    <PlanTimeline
                      steps={recentMission.current_plan.steps}
                      executionHistory={recentMission.execution_history}
                    />
                  </div>
                )}
              </div>
            )}
          </section>
        </GlassCard>

        <GlassCard
          title="Latest Memory"
          titleAction={
            <a href="/memory" className="home-page__view-all">
              View All <span aria-hidden="true">→</span>
            </a>
          }
          className="home-page__latest-memory"
        >
          <section aria-label="Latest Memory">
            {recentMemories.length === 0 && <p>No memories yet.</p>}
            {recentMemories.length > 0 && (
              <ul className="home-page__memory-list">
                {recentMemories.map((entry) => (
                  <li key={entry.memory_id} className="home-page__memory-row">
                    <span className="home-page__memory-icon" aria-hidden="true">
                      <MemoryIcon name={(entry.memory_type as MemoryIconName) ?? "all"} />
                    </span>
                    <span className="home-page__memory-content">{memoryText(entry)}</span>
                    <span className="home-page__memory-age">{formatMemoryAge(entry.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </GlassCard>
      </div>

      <section className="home-page__try-strip" aria-label="Try saying something">
        <div className="home-page__try-strip-text">
          <p className="home-page__try-strip-title">Try saying something</p>
          <div className="milo-example-strip">
            {QUICK_EXAMPLES.map((example) => (
              <span key={example} className="milo-example-chip">
                {EXAMPLE_ICON[example] ? <HomeIcon name={EXAMPLE_ICON[example]} /> : null}
                {example}
              </span>
            ))}
          </div>
        </div>
        <div className="home-page__try-strip-milo">
          <div className="home-page__try-strip-bubble">
            <MiloStateIndicator state={miloState} className="home-page__try-strip-status" />
            <span className="home-page__try-strip-arrow" aria-hidden="true">
              ⤷
            </span>
          </div>
          <MiloAvatar state={miloState} size="md" />
        </div>
      </section>
    </main>
  );
}

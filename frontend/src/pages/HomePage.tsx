// HomePage.tsx
//
// Purpose
// -------
// "Who is MILO?" / "Can I talk to MILO?" -- spec's Home page. Composes
// `TalkToMilo` (shared with Mission Control) for the text/speech input
// and quick examples, `AgentStatusList` (shared with Mission Control/
// Lab) for "MILO At a Glance," and reads `TaskContext.history` (`GET
// /tasks`) directly for "Recent Mission"/"Latest Memory" -- both are
// real data or an explicit empty state, never a fabricated number
// (spec Part 12/13).
//
// Phase 8.2 visual pass: hero (MiloCharacter + greeting) and a 3-card
// glance/mission/memory row, matching the Home mockup's composition.
// `AgentStatusList`'s per-agent rows already avoid fabricating
// "Online" (see that component's docstring) -- this page does not add
// a second, invented "All systems operational" claim on top of that;
// the "systems" summary below is instead computed from the same real
// per-agent states already rendered.
import { AgentStatusList } from "../components/AgentStatusList";
import { GlassCard } from "../components/GlassCard";
import { MiloCharacter } from "../components/MiloCharacter";
import { StatusPill } from "../components/StatusPill";
import { TalkToMilo } from "../components/TalkToMilo";
import { useAgents } from "../state/AgentsContext";
import { useTask } from "../state/TaskContext";

const QUICK_EXAMPLES = [
  "Find the apple",
  "Bring me the red mug",
  "Put the bottle on the table",
  "Where did you see the mug last time?",
];

const GLANCE_AGENTS = ["vision", "memory", "planner", "navigation", "execution"];

function formatElapsed(totalMs: number | null | undefined): string | null {
  if (totalMs == null) return null;
  const seconds = totalMs / 1000;
  return seconds < 60 ? `${seconds.toFixed(1)}s` : `${(seconds / 60).toFixed(1)}m`;
}

export function HomePage() {
  const { history, historyStatus } = useTask();
  const { agents, status: agentsStatus } = useAgents();
  const recentMission = history[0] ?? null;
  const latestMemory = recentMission
    ? (recentMission.created_memories[0] ?? recentMission.retrieved_memories[0] ?? null)
    : null;

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

  return (
    <main aria-label="Home" className="home-page">
      <section className="home-page__hero">
        <div className="home-page__intro">
          <h1>Home</h1>
          <p className="home-page__greeting-eyebrow">Hi, I'm</p>
          <p className="home-page__greeting">MILO</p>
          <p className="home-page__fullname">Memory Integrated Language Oriented Robot</p>
          <p className="home-page__description">
            I see the world, understand what you say, remember what I learn, and figure out the
            best way to help.
          </p>
        </div>
        <div className="home-page__character">
          <MiloCharacter state="idle" size="lg" />
        </div>
      </section>

      <TalkToMilo quickExamples={QUICK_EXAMPLES} />

      <div className="home-page__grid">
        <GlassCard title="MILO At a Glance" className="home-page__glance">
          <section aria-label="MILO At a Glance">
            <StatusPill tone={hasErrorAgent ? "danger" : "success"} dot>
              {systemsSummary}
            </StatusPill>
            <AgentStatusList names={GLANCE_AGENTS} />
          </section>
        </GlassCard>

        <GlassCard title="Recent Mission" className="home-page__recent-mission">
          <section aria-label="Recent Mission">
            {historyStatus === "loading" && !recentMission && <p>Loading...</p>}
            {historyStatus !== "loading" && !recentMission && <p>No missions yet.</p>}
            {recentMission && (
              <div className="home-page__mission-card">
                <p className="home-page__mission-request">{recentMission.user_request}</p>
                <p className="home-page__mission-status">Status: {recentMission.status}</p>
                {formatElapsed(recentMission.metrics.total_ms) && (
                  <p className="home-page__mission-elapsed">
                    Took {formatElapsed(recentMission.metrics.total_ms)}
                  </p>
                )}
              </div>
            )}
          </section>
        </GlassCard>

        <GlassCard title="Latest Memory" className="home-page__latest-memory">
          <section aria-label="Latest Memory">
            {!latestMemory && <p>No memories yet.</p>}
            {latestMemory && (
              <p className="home-page__memory-content">
                {typeof latestMemory.content === "string" ? latestMemory.content : "One new memory."}
                {latestMemory.memory_type ? ` (${latestMemory.memory_type})` : ""}
              </p>
            )}
          </section>
        </GlassCard>
      </div>
    </main>
  );
}

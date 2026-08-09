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
import { TalkToMilo } from "../components/TalkToMilo";
import { AgentStatusList } from "../components/AgentStatusList";
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
  const recentMission = history[0] ?? null;
  const latestMemory = recentMission
    ? (recentMission.created_memories[0] ?? recentMission.retrieved_memories[0] ?? null)
    : null;

  return (
    <main aria-label="Home" className="home-page">
      <section className="home-page__intro">
        <h1>Home</h1>
        <p className="home-page__greeting">Hi, I'm MILO.</p>
        <p className="home-page__fullname">Memory Integrated Language Oriented Robot</p>
        <p className="home-page__description">
          I perceive the scene in front of me, remember what I've learned, plan a sequence of
          actions to reach a goal, navigate a simulated home, act on it, reflect on what happened,
          replan when something goes wrong, and remember the outcome for next time.
        </p>
      </section>

      <TalkToMilo quickExamples={QUICK_EXAMPLES} />

      <section aria-label="MILO At a Glance" className="home-page__glance">
        <h2>MILO At a Glance</h2>
        <AgentStatusList names={GLANCE_AGENTS} />
      </section>

      <section aria-label="Recent Mission" className="home-page__recent-mission">
        <h2>Recent Mission</h2>
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

      <section aria-label="Latest Memory" className="home-page__latest-memory">
        <h2>Latest Memory</h2>
        {!latestMemory && <p>No memories yet.</p>}
        {latestMemory && (
          <p className="home-page__memory-content">
            {typeof latestMemory.content === "string" ? latestMemory.content : "One new memory."}
            {latestMemory.memory_type ? ` (${latestMemory.memory_type})` : ""}
          </p>
        )}
      </section>
    </main>
  );
}

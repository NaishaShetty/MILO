// LabPage.tsx
//
// Purpose
// -------
// "How is the system working technically?" -- the research/
// experimentation dashboard. Phase 8.2 wires this to the real MILO Lab
// API (`backend/api/routes/lab.py`): "Recent Experiments" lists real
// persisted benchmark runs and can trigger a new one; "My Sandbox" is
// a real parse+plan dry run (never touches the simulator); "Lab Stats"
// comes from the backend's own aggregation. "Tune Parameters" links to
// Settings' real read-only config display instead of a fake toggle --
// see `backend/api/routes/lab.py`'s module docstring for why config
// isn't live-mutable.
//
// Visual refinement pass: hero + 3-column dashboard (Quick Start |
// Recent Experiments | Sandbox/Stats) matching the Lab mockup's
// composition. A few mockup affordances have no real backing feature
// and are deliberately omitted rather than faked: "Upload Custom
// Data" (no upload endpoint), "View All Tools" (no tools index),
// "Open Playground" as a separate destination (the Sandbox *is* the
// playground here). "Reset All" and the bottom "Suggest an
// Experiment" CTA are wired to real, if modest, actions (clearing
// local sandbox state; focusing the real sandbox input) rather than
// left as inert copies of the mockup. Every number/string rendered
// still comes from `listExperiments`/`getLabStats`/`runSandbox` -- see
// each field's own comment below for why it maps the way it does.
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import type { FormEvent } from "react";

import { AgentStatusList } from "../components/AgentStatusList";
import { GlassCard } from "../components/GlassCard";
import { LabIcon } from "../components/LabIcons";
import { MiloAvatar } from "../components/MiloAvatar";
import { MiloWordmark } from "../components/MiloWordmark";
import { StatusPill } from "../components/StatusPill";
import { getLabStats, listExperiments, runPerceptionExperiment, runSandbox } from "../api/lab";
import type { ExperimentSummary, LabStatsResponse, SandboxResponse } from "../api/labTypes";
import { useAgents } from "../state/AgentsContext";
import { useMiloState } from "../state/MiloStateContext";
import { useTask } from "../state/TaskContext";
import { usePolling } from "../hooks/usePolling";

const ALL_AGENTS = ["vision", "memory", "planner", "navigation", "execution", "reflection", "speech"];
const POLL_INTERVAL_MS = 10000;

function formatPercent(fraction: number | null): string {
  if (fraction == null) return "unavailable";
  return `${(fraction * 100).toFixed(0)}%`;
}

// A run only appears in `GET /lab/experiments` once its result store
// has finished writing `summary.json` (see `_list_experiment_runs` in
// `backend/api/routes/lab.py`) -- so every listed row genuinely did
// complete. That's the one true thing this data supports; the
// per-benchmark metrics inside `result` (depth/tracking dicts for
// perception, an unknown shape for language) have no common
// pass/fail or single-score field, so Status stays this honest
// "Completed" rather than an invented Success/Partial/Failed, and
// Result stays "--" rather than an invented percentage.
function ExperimentRow({ experiment }: { experiment: ExperimentSummary }) {
  return (
    <div className="lab-page__table-row" role="row">
      <span className="lab-page__table-cell lab-page__exp-name" role="cell">
        <span className="lab-page__exp-icon" aria-hidden="true">
          <LabIcon name="flask" />
        </span>
        <span>{experiment.run_id}</span>
      </span>
      <span className="lab-page__table-cell" role="cell">
        <StatusPill tone="info">{experiment.experiment_type}</StatusPill>
      </span>
      <span className="lab-page__table-cell" role="cell">
        <StatusPill tone="neutral">Completed</StatusPill>
      </span>
      <span className="lab-page__table-cell lab-page__exp-time" role="cell">
        {new Date(experiment.timestamp).toLocaleString()}
      </span>
      <span className="lab-page__table-cell lab-page__exp-result" role="cell">
        —
      </span>
    </div>
  );
}

export function LabPage() {
  const { activeTaskId, events } = useTask();
  const { agents, status: agentsStatus } = useAgents();
  const miloState = useMiloState();

  const experimentsResult = usePolling(listExperiments, { intervalMs: POLL_INTERVAL_MS, enabled: true });
  const statsResult = usePolling(getLabStats, { intervalMs: POLL_INTERVAL_MS, enabled: true });

  const [runningPerception, setRunningPerception] = useState(false);
  const [instruction, setInstruction] = useState("");
  const [sandboxState, setSandboxState] = useState<
    | { status: "idle" }
    | { status: "loading" }
    | { status: "success"; data: SandboxResponse }
    | { status: "error"; message: string }
  >({ status: "idle" });
  const sandboxInputRef = useRef<HTMLInputElement>(null);

  const stats: LabStatsResponse = statsResult.data ?? {
    experiments_run: 0,
    task_success_rate: null,
    total_actions: 0,
    memories_created: 0,
    tasks_run: 0,
  };

  async function handleRunPerception() {
    setRunningPerception(true);
    try {
      await runPerceptionExperiment();
      experimentsResult.refresh();
      statsResult.refresh();
    } finally {
      setRunningPerception(false);
    }
  }

  async function handleSandboxSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = instruction.trim();
    if (!trimmed || sandboxState.status === "loading") return;
    setSandboxState({ status: "loading" });
    try {
      const data = await runSandbox(trimmed);
      setSandboxState({ status: "success", data });
    } catch (error) {
      setSandboxState({
        status: "error",
        message: error instanceof Error ? error.message : "Sandbox request failed.",
      });
    }
  }

  // Real, local reset -- no backend "reset" endpoint exists, but
  // clearing this page's own sandbox state genuinely is the reset.
  function handleSandboxReset() {
    setInstruction("");
    setSandboxState({ status: "idle" });
  }

  function focusSandboxInput() {
    sandboxInputRef.current?.focus();
  }

  const experiments = experimentsResult.data?.experiments ?? [];

  return (
    <main aria-label="MILO Lab" className="lab-page">
      <h1 className="sr-only">MILO Lab</h1>

      <section className="lab-page__hero">
        <div className="lab-page__hero-character">
          <div className="milo-glow-orb" aria-hidden="true" />
          <MiloAvatar state={miloState} size="lg" />
        </div>

        <div className="lab-page__hero-copy">
          <p className="lab-page__hero-title">
            <MiloWordmark className="lab-page__hero-wordmark" /> Lab
          </p>
          <p className="lab-page__tagline">My playground. Your experiments. Our future.</p>
          <p className="lab-page__hero-description">
            Test ideas, tweak things, and see what MILO does with them -- every run here is real,
            never a canned demo.
          </p>
        </div>

        <div className="lab-page__hero-actions">
          <a href="#lab-experiments" className="lab-page__hero-card">
            <span className="lab-page__hero-card-icon" aria-hidden="true">
              <LabIcon name="flask" />
            </span>
            <span className="lab-page__hero-card-title">Experiment Freely</span>
            <span className="lab-page__hero-card-desc">Try new prompts, tasks, and scenarios.</span>
            <span className="lab-page__hero-card-cta">
              Start Experiment <LabIcon name="arrow-right" />
            </span>
          </a>
          <a href="#lab-sandbox" className="lab-page__hero-card">
            <span className="lab-page__hero-card-icon" aria-hidden="true">
              <LabIcon name="code" />
            </span>
            <span className="lab-page__hero-card-title">Tinker &amp; Build</span>
            <span className="lab-page__hero-card-desc">Dry-run instructions in the sandbox.</span>
            <span className="lab-page__hero-card-cta">
              Open Sandbox <LabIcon name="arrow-right" />
            </span>
          </a>
          <a href="#lab-stats" className="lab-page__hero-card">
            <span className="lab-page__hero-card-icon" aria-hidden="true">
              <LabIcon name="chart" />
            </span>
            <span className="lab-page__hero-card-title">Measure &amp; Improve</span>
            <span className="lab-page__hero-card-desc">Track results and lab-wide stats.</span>
            <span className="lab-page__hero-card-cta">
              View Stats <LabIcon name="arrow-right" />
            </span>
          </a>
        </div>
      </section>

      <div className="lab-page__grid">
        <aside className="lab-page__quick-start">
          <GlassCard title="Quick Start">
            <div className="lab-page__quick-list">
              <Link to="/" className="lab-page__quick-item">
                <span className="lab-page__quick-icon" aria-hidden="true">
                  <LabIcon name="chat" />
                </span>
                <span className="lab-page__quick-body">
                  <span className="lab-page__quick-title">Try a New Instruction</span>
                  <span className="lab-page__quick-desc">See how MILO handles it.</span>
                </span>
                <LabIcon name="arrow-right" className="lab-page__quick-arrow" />
              </Link>
              <Link to="/mission-control" className="lab-page__quick-item">
                <span className="lab-page__quick-icon" aria-hidden="true">
                  <LabIcon name="cube" />
                </span>
                <span className="lab-page__quick-body">
                  <span className="lab-page__quick-title">Test a Scenario</span>
                  <span className="lab-page__quick-desc">Pick a mission and watch it run.</span>
                </span>
                <LabIcon name="arrow-right" className="lab-page__quick-arrow" />
              </Link>
              <Link to="/settings" className="lab-page__quick-item">
                <span className="lab-page__quick-icon" aria-hidden="true">
                  <LabIcon name="sliders" />
                </span>
                <span className="lab-page__quick-body">
                  <span className="lab-page__quick-title">Tune Parameters</span>
                  <span className="lab-page__quick-desc">Review memory, planning, and vision settings.</span>
                </span>
                <LabIcon name="arrow-right" className="lab-page__quick-arrow" />
              </Link>
            </div>
          </GlassCard>
        </aside>

        <section className="lab-page__experiments" id="lab-experiments">
          <GlassCard title="Recent Experiments" className="lab-page__experiments-card">
            <section aria-label="Recent Experiments">
              <div className="lab-page__table-wrap">
                <div className="lab-page__table" role="table" aria-label="Recent experiments">
                  <div className="lab-page__table-row lab-page__table-row--head" role="row">
                    <span className="lab-page__table-cell" role="columnheader">
                      Experiment
                    </span>
                    <span className="lab-page__table-cell" role="columnheader">
                      Type
                    </span>
                    <span className="lab-page__table-cell" role="columnheader">
                      Status
                    </span>
                    <span className="lab-page__table-cell" role="columnheader">
                      Last Run
                    </span>
                    <span className="lab-page__table-cell" role="columnheader">
                      Result
                    </span>
                  </div>

                  {experimentsResult.status !== "loading" && experiments.length === 0 && (
                    <p className="lab-page__table-empty">No experiments have been run yet.</p>
                  )}

                  {experiments.map((experiment) => (
                    <ExperimentRow key={experiment.run_id} experiment={experiment} />
                  ))}
                </div>
              </div>

              <button
                type="button"
                className="lab-page__run-experiment"
                onClick={() => void handleRunPerception()}
                disabled={runningPerception}
              >
                <LabIcon name="plus" />
                {runningPerception ? "Running..." : "Run Perception Benchmark"}
              </button>
            </section>
          </GlassCard>
        </section>

        <aside className="lab-page__side">
          <GlassCard
            title="My Sandbox"
            titleAction={
              <button type="button" className="lab-page__reset" onClick={handleSandboxReset}>
                <LabIcon name="reset" /> Reset All
              </button>
            }
            className="lab-page__sandbox-card"
            id="lab-sandbox"
          >
            <section aria-label="My Sandbox">
              <p className="lab-page__readonly-note">
                Dry run only -- parses and plans a real instruction without touching the simulator.
              </p>
              <form onSubmit={handleSandboxSubmit} className="lab-page__sandbox-form">
                <label htmlFor="lab-sandbox-input">Try an instruction</label>
                <div className="lab-page__sandbox-row">
                  <input
                    id="lab-sandbox-input"
                    ref={sandboxInputRef}
                    type="text"
                    placeholder="Put the apple in the refrigerator"
                    value={instruction}
                    onChange={(event) => setInstruction(event.target.value)}
                    disabled={sandboxState.status === "loading"}
                  />
                  <button
                    type="submit"
                    disabled={sandboxState.status === "loading" || instruction.trim().length === 0}
                  >
                    {sandboxState.status === "loading" ? "Running..." : "Run"}
                  </button>
                </div>
              </form>

              <div className="lab-page__terminal" aria-live="polite">
                {sandboxState.status === "idle" && (
                  <p className="lab-page__terminal-line lab-page__terminal-line--muted">Sandbox is idle.</p>
                )}
                {sandboxState.status === "loading" && (
                  <p className="lab-page__terminal-line lab-page__terminal-line--muted">
                    &gt; Running dry run...
                  </p>
                )}
                {sandboxState.status === "error" && (
                  <p className="lab-page__terminal-line lab-page__terminal-line--error" role="alert">
                    &gt; Error: {sandboxState.message}
                  </p>
                )}
                {sandboxState.status === "success" && (
                  <>
                    <p className="lab-page__terminal-line">
                      <span className="lab-page__terminal-prefix">&gt; Parsed:</span>{" "}
                      <span>
                        {sandboxState.data.parsed.task_type === "single"
                          ? `${sandboxState.data.parsed.goal ?? "unknown goal"} ${sandboxState.data.parsed.object ?? ""}`.trim()
                          : "Multi-step task (not supported in sandbox)"}
                      </span>
                    </p>
                    <p className="lab-page__terminal-line">
                      <span className="lab-page__terminal-prefix">&gt; Plan:</span>{" "}
                      <span>
                        {sandboxState.data.unsupported_reason
                          ? sandboxState.data.unsupported_reason
                          : sandboxState.data.plan?.plan
                            ? `${sandboxState.data.plan.plan.steps.length} step(s), ${sandboxState.data.plan.planner_type}`
                            : "No plan produced."}
                      </span>
                    </p>
                  </>
                )}
              </div>
            </section>
          </GlassCard>

          <GlassCard title="Lab Stats" className="lab-page__stats-card" id="lab-stats">
            <section aria-label="Lab Stats">
              <ul className="lab-page__stats">
                <li className="lab-page__stat">
                  <span className="lab-page__stat-visual" aria-hidden="true">
                    <LabIcon name="flask" className="lab-page__stat-icon" />
                    <span className="lab-page__stat-label">Experiments Run</span>
                    <span className="lab-page__stat-value">{stats.experiments_run}</span>
                  </span>
                  <span className="sr-only">Experiments run: {stats.experiments_run}</span>
                </li>
                <li className="lab-page__stat">
                  <span className="lab-page__stat-visual" aria-hidden="true">
                    <LabIcon name="target" className="lab-page__stat-icon" />
                    <span className="lab-page__stat-label">Tasks Run</span>
                    <span className="lab-page__stat-value">{stats.tasks_run}</span>
                  </span>
                  <span className="sr-only">Tasks run: {stats.tasks_run}</span>
                </li>
                <li className="lab-page__stat">
                  <span className="lab-page__stat-visual" aria-hidden="true">
                    <LabIcon name="target" className="lab-page__stat-icon" />
                    <span className="lab-page__stat-label">Success Rate</span>
                    <span className="lab-page__stat-value">{formatPercent(stats.task_success_rate)}</span>
                  </span>
                  <span className="sr-only">Success rate: {formatPercent(stats.task_success_rate)}</span>
                </li>
                <li className="lab-page__stat">
                  <span className="lab-page__stat-visual" aria-hidden="true">
                    <LabIcon name="lightning" className="lab-page__stat-icon" />
                    <span className="lab-page__stat-label">Total Actions</span>
                    <span className="lab-page__stat-value">{stats.total_actions}</span>
                  </span>
                  <span className="sr-only">Total actions: {stats.total_actions}</span>
                </li>
                <li className="lab-page__stat">
                  <span className="lab-page__stat-visual" aria-hidden="true">
                    <LabIcon name="memory" className="lab-page__stat-icon" />
                    <span className="lab-page__stat-label">Memories Created</span>
                    <span className="lab-page__stat-value">{stats.memories_created}</span>
                  </span>
                  <span className="sr-only">Memories created: {stats.memories_created}</span>
                </li>
              </ul>
            </section>
          </GlassCard>
        </aside>
      </div>

      <GlassCard title="Technical System Information" className="lab-page__technical">
        <section aria-label="Technical System Information">
          <p>Active agents:</p>
          <AgentStatusList names={ALL_AGENTS} />
          <dl className="lab-page__technical-list">
            <dt>Simulator / environment</dt>
            <dd>
              {agentsStatus === "success" && agents.length > 0
                ? "Orchestrator/simulator reachable (agents registered)"
                : "Not reachable — no agents registered (simulator likely disabled)"}
            </dd>
            <dt>Task state</dt>
            <dd>{activeTaskId ? activeTaskId : "No active task"}</dd>
            <dt>Event state</dt>
            <dd>{events.length} event(s) recorded for the active task</dd>
          </dl>
        </section>
      </GlassCard>

      <section className="lab-page__cta">
        <div className="lab-page__cta-copy">
          <span className="lab-page__cta-icon" aria-hidden="true">
            <LabIcon name="lightbulb" />
          </span>
          <div>
            <p className="lab-page__cta-title">Have a crazy idea?</p>
            <p className="lab-page__cta-desc">Tell MILO what you want to try in the sandbox above.</p>
          </div>
        </div>
        <button type="button" className="lab-page__cta-button" onClick={focusSandboxInput}>
          Suggest an Experiment <LabIcon name="arrow-right" />
        </button>
      </section>
    </main>
  );
}

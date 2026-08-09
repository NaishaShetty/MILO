// LabPage.tsx
//
// Purpose
// -------
// "How is the system working technically?" -- the research/
// experimentation dashboard. Phase 8.2 wires this to the real MILO Lab
// API (`backend/api/routes/lab.py`): "Recent Experiments" lists real
// persisted benchmark runs and can trigger a new one; "My Sandbox" is
// a real parse+plan dry run (never touches the simulator); "Lab Stats"
// comes from the backend's own aggregation. "Tune Parameters"/"Upload
// Custom Data" are intentionally NOT built as full features here --
// see `backend/api/routes/lab.py`'s module docstring for why (env-
// derived config isn't live-mutable without a real architecture
// change) -- "Tune Parameters" links to Settings' real read-only
// config display instead of a fake toggle.
import { useState } from "react";
import { Link } from "react-router-dom";
import type { FormEvent } from "react";

import { AgentStatusList } from "../components/AgentStatusList";
import { GlassCard } from "../components/GlassCard";
import { StatusPill } from "../components/StatusPill";
import { getLabStats, listExperiments, runPerceptionExperiment, runSandbox } from "../api/lab";
import type { ExperimentSummary, LabStatsResponse, SandboxResponse } from "../api/labTypes";
import { useAgents } from "../state/AgentsContext";
import { useTask } from "../state/TaskContext";
import { usePolling } from "../hooks/usePolling";

const ALL_AGENTS = ["vision", "memory", "planner", "navigation", "execution", "reflection", "speech"];
const POLL_INTERVAL_MS = 10000;

function formatPercent(fraction: number | null): string {
  if (fraction == null) return "unavailable";
  return `${(fraction * 100).toFixed(0)}%`;
}

function ExperimentRow({ experiment }: { experiment: ExperimentSummary }) {
  return (
    <li className="lab-page__experiment">
      <span className="lab-page__experiment-id">{experiment.run_id}</span>
      <StatusPill tone="info">{experiment.experiment_type}</StatusPill>
      <span className="lab-page__experiment-time">
        {new Date(experiment.timestamp).toLocaleString()}
      </span>
    </li>
  );
}

export function LabPage() {
  const { activeTaskId, events } = useTask();
  const { agents, status: agentsStatus } = useAgents();

  const experimentsResult = usePolling(listExperiments, { intervalMs: POLL_INTERVAL_MS, enabled: true });
  const statsResult = usePolling(getLabStats, { intervalMs: POLL_INTERVAL_MS, enabled: true });

  const [runningPerception, setRunningPerception] = useState(false);
  const [instruction, setInstruction] = useState("");
  const [sandboxState, setSandboxState] = useState<
    { status: "idle" } | { status: "loading" } | { status: "success"; data: SandboxResponse } | { status: "error"; message: string }
  >({ status: "idle" });

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

  return (
    <main aria-label="MILO Lab" className="lab-page">
      <h1>MILO Lab</h1>

      <GlassCard title="Quick Start" className="lab-page__section">
        <section aria-label="Quick Start">
          <div className="lab-page__quick-start">
            <Link to="/" className="lab-page__action">
              Try a New Instruction
            </Link>
            <Link to="/mission-control" className="lab-page__action">
              Test a Scenario
            </Link>
            <Link to="/settings" className="lab-page__action">
              Tune Parameters
            </Link>
          </div>
        </section>
      </GlassCard>

      <GlassCard title="Recent Experiments" className="lab-page__section">
        <section aria-label="Recent Experiments">
          <button
            type="button"
            className="lab-page__run-experiment"
            onClick={() => void handleRunPerception()}
            disabled={runningPerception}
          >
            {runningPerception ? "Running..." : "Run Perception Benchmark"}
          </button>
          {experimentsResult.status !== "loading" && experimentsResult.data?.experiments.length === 0 && (
            <p>No experiments have been run yet.</p>
          )}
          {experimentsResult.data && experimentsResult.data.experiments.length > 0 && (
            <ul className="lab-page__experiments">
              {experimentsResult.data.experiments.map((experiment) => (
                <ExperimentRow key={experiment.run_id} experiment={experiment} />
              ))}
            </ul>
          )}
        </section>
      </GlassCard>

      <GlassCard title="My Sandbox" className="lab-page__section">
        <section aria-label="My Sandbox">
          <p className="lab-page__readonly-note">
            Dry run only -- parses and plans a real instruction without touching the simulator.
          </p>
          <form onSubmit={handleSandboxSubmit} className="lab-page__sandbox-form">
            <label htmlFor="lab-sandbox-input">Try an instruction</label>
            <div className="lab-page__sandbox-row">
              <input
                id="lab-sandbox-input"
                type="text"
                placeholder="Put the apple in the refrigerator"
                value={instruction}
                onChange={(event) => setInstruction(event.target.value)}
                disabled={sandboxState.status === "loading"}
              />
              <button type="submit" disabled={sandboxState.status === "loading" || instruction.trim().length === 0}>
                {sandboxState.status === "loading" ? "Running..." : "Run"}
              </button>
            </div>
          </form>
          {sandboxState.status === "error" && (
            <p className="memory-page__error" role="alert">
              {sandboxState.message}
            </p>
          )}
          {sandboxState.status === "success" && (
            <dl className="lab-page__sandbox">
              <dt>Parsed task</dt>
              <dd>
                {sandboxState.data.parsed.task_type === "single"
                  ? `${sandboxState.data.parsed.goal ?? "unknown goal"} ${sandboxState.data.parsed.object ?? ""}`.trim()
                  : "Multi-step task (not supported in sandbox)"}
              </dd>
              <dt>Plan</dt>
              <dd>
                {sandboxState.data.unsupported_reason
                  ? sandboxState.data.unsupported_reason
                  : sandboxState.data.plan?.plan
                    ? `${sandboxState.data.plan.plan.steps.length} step(s), ${sandboxState.data.plan.planner_type}`
                    : "No plan produced."}
              </dd>
            </dl>
          )}
        </section>
      </GlassCard>

      <GlassCard title="Lab Stats" className="lab-page__section">
        <section aria-label="Lab Stats">
          <ul className="lab-page__stats">
            <li>Experiments run: {stats.experiments_run}</li>
            <li>Tasks run: {stats.tasks_run}</li>
            <li>Success rate: {formatPercent(stats.task_success_rate)}</li>
            <li>Total actions: {stats.total_actions}</li>
            <li>Memories created: {stats.memories_created}</li>
          </ul>
        </section>
      </GlassCard>

      <GlassCard title="Technical System Information" className="lab-page__section">
        <section aria-label="Technical System Information">
          <p>Active agents:</p>
          <AgentStatusList names={ALL_AGENTS} />
          <dl className="lab-page__technical">
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
    </main>
  );
}

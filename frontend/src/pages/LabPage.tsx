// LabPage.tsx
//
// Purpose
// -------
// "How is the system working technically?" -- the research/debugging
// dashboard. Every number here is computed from real data already in
// `TaskContext` (`history`, `activeTask`) or `AgentsContext`; there is
// no experiment-tracking system anywhere in this repo (Session 3
// audit), so "Recent Experiments" says so plainly instead of
// fabricating a history, and shows the real Lab Stats in its place, as
// the plan calls for.
import { useMemo } from "react";
import { Link } from "react-router-dom";

import { AgentStatusList } from "../components/AgentStatusList";
import { useAgents } from "../state/AgentsContext";
import { useTask } from "../state/TaskContext";

const ALL_AGENTS = ["vision", "memory", "planner", "navigation", "execution", "reflection", "speech"];

function formatMs(ms: number | null): string {
  if (ms == null) return "unavailable";
  return ms < 1000 ? `${ms.toFixed(0)} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function formatPercent(fraction: number | null): string {
  if (fraction == null) return "unavailable";
  return `${(fraction * 100).toFixed(0)}%`;
}

export function LabPage() {
  const { history, activeTask, activeTaskId, events } = useTask();
  const { agents, status: agentsStatus } = useAgents();

  const stats = useMemo(() => {
    const tasksRun = history.length;
    if (tasksRun === 0) {
      return {
        tasksRun: 0,
        successRate: null as number | null,
        totalActions: 0,
        memoriesCreated: 0,
        failures: 0,
        replans: 0,
        avgTaskMs: null as number | null,
      };
    }
    const successCount = history.filter((task) => task.metrics.success).length;
    const totalActions = history.reduce((sum, task) => sum + task.metrics.actions, 0);
    const memoriesCreated = history.reduce((sum, task) => sum + task.created_memories.length, 0);
    const failures = history.reduce((sum, task) => sum + task.metrics.failures, 0);
    const replans = history.reduce((sum, task) => sum + task.metrics.replans, 0);
    const durations = history
      .map((task) => task.metrics.total_ms)
      .filter((ms): ms is number => ms != null);
    const avgTaskMs = durations.length > 0 ? durations.reduce((a, b) => a + b, 0) / durations.length : null;

    return {
      tasksRun,
      successRate: successCount / tasksRun,
      totalActions,
      memoriesCreated,
      failures,
      replans,
      avgTaskMs,
    };
  }, [history]);

  const latestPlannerType = history.find((task) => task.current_plan)?.current_plan?.planner_type ?? null;

  return (
    <main aria-label="MILO Lab" className="lab-page">
      <h1>🔬 MILO Lab</h1>

      <section aria-label="Quick Start" className="lab-page__section">
        <h2>Quick Start</h2>
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

      <section aria-label="Recent Experiments" className="lab-page__section">
        <h2>Recent Experiments</h2>
        <p>No experiment framework connected — showing live task metrics instead (Lab Stats below).</p>
      </section>

      <section aria-label="My Sandbox" className="lab-page__section">
        <h2>My Sandbox</h2>
        {!activeTaskId && <p>No active task.</p>}
        {activeTask && (
          <dl className="lab-page__sandbox">
            <dt>Current task</dt>
            <dd>{activeTask.user_request}</dd>
            <dt>Current plan</dt>
            <dd>
              {activeTask.current_plan
                ? `${activeTask.current_plan.steps.length} step(s), ${activeTask.current_plan.planner_type}`
                : "No plan yet."}
            </dd>
            <dt>Current observation</dt>
            <dd>{activeTask.observations.length > 0 ? `${activeTask.observations.length} observation(s) recorded` : "None yet."}</dd>
            <dt>Current action</dt>
            <dd>{activeTask.current_step != null ? `Step ${activeTask.current_step}` : "None yet."}</dd>
            <dt>Status</dt>
            <dd>{activeTask.status}</dd>
          </dl>
        )}
      </section>

      <section aria-label="Lab Stats" className="lab-page__section">
        <h2>Lab Stats</h2>
        <ul className="lab-page__stats">
          <li>Tasks run: {stats.tasksRun}</li>
          <li>Success rate: {formatPercent(stats.successRate)}</li>
          <li>Total actions: {stats.totalActions}</li>
          <li>Memories created: {stats.memoriesCreated}</li>
          <li>Failures: {stats.failures}</li>
          <li>Replans: {stats.replans}</li>
          <li>Average task time: {formatMs(stats.avgTaskMs)}</li>
        </ul>
      </section>

      <section aria-label="Technical System Information" className="lab-page__section">
        <h2>Technical System Information</h2>
        <p>Active agents:</p>
        <AgentStatusList names={ALL_AGENTS} />
        <dl className="lab-page__technical">
          <dt>Planner</dt>
          <dd>{latestPlannerType ?? "unknown (no task has run yet)"}</dd>
          <dt>Simulator / environment</dt>
          <dd>
            {agentsStatus === "success" && agents.length > 0
              ? "Orchestrator/simulator reachable (agents registered)"
              : "Not reachable — no agents registered (simulator likely disabled)"}
          </dd>
          <dt>Task state</dt>
          <dd>{activeTaskId ? `${activeTaskId} (${activeTask?.status ?? "unknown"})` : "No active task"}</dd>
          <dt>Event state</dt>
          <dd>{events.length} event(s) recorded for the active task</dd>
        </dl>
      </section>
    </main>
  );
}

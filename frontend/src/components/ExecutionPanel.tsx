// ExecutionPanel.tsx
//
// Purpose
// -------
// Top-level Phase 5 UI panel: given one validated `Plan` (the output
// of `PlannerPanel`'s "Generate Plan" action), lets the user execute
// it against the running simulator and watch it happen -- section 16's
// full mock: robot state, current plan (with live step status),
// current action, execution log, and errors. Rendered by
// `PlannerPanel.tsx` directly beneath its own "Current Plan"/
// "Validation" sections once a plan exists, mirroring how
// `PlannerPanel` itself is rendered beneath `TaskCard` in
// `ResultView.tsx` -- each panel takes the previous phase's real
// output as a prop, never re-fetches or duplicates it.
//
// Why this polls instead of using a websocket/SSE stream
// ------------------------------------------------------------
// `POST /api/v1/execution/start` runs the plan on a backend thread and
// returns immediately (see `api/routes/execution.py`'s docstring);
// this component polls `GET /api/v1/execution/{id}` on a fixed
// interval until the execution reaches a terminal status. A
// streaming/websocket transport would add a second network primitive
// to this frontend for a research-dashboard polling need that a
// simple interval already satisfies -- consistent with this project's
// "do not introduce unnecessary complexity" principle.
import { useEffect, useRef, useState } from "react";
import {
  cancelExecution,
  ExecutionApiError,
  getExecution,
  startExecution,
} from "../api/execution";
import type { ExecutionRecord } from "../api/executionTypes";
import { TERMINAL_EXECUTION_STATUSES } from "../api/executionTypes";
import type { Plan } from "../api/plannerTypes";
import { ExecutionLog } from "./ExecutionLog";
import { ExecutionStepsList } from "./ExecutionStepsList";

const POLL_INTERVAL_MS = 500;

const STATUS_LABEL: Record<string, string> = {
  pending: "PENDING",
  running: "RUNNING",
  success: "SUCCESS",
  failed: "FAILED",
  cancelled: "CANCELLED",
};

type PanelState =
  | { phase: "idle" }
  | { phase: "starting" }
  | { phase: "polling"; record: ExecutionRecord }
  | { phase: "done"; record: ExecutionRecord }
  | { phase: "error"; message: string };

interface ExecutionPanelProps {
  plan: Plan;
}

export function ExecutionPanel({ plan }: ExecutionPanelProps) {
  const [state, setState] = useState<PanelState>({ phase: "idle" });
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, []);

  function schedulePoll(executionId: string) {
    pollTimer.current = setTimeout(async () => {
      try {
        const record = await getExecution(executionId);
        if (TERMINAL_EXECUTION_STATUSES.includes(record.status)) {
          setState({ phase: "done", record });
        } else {
          setState({ phase: "polling", record });
          schedulePoll(executionId);
        }
      } catch (error) {
        const message =
          error instanceof ExecutionApiError ? error.message : "Lost connection while polling execution status.";
        setState({ phase: "error", message });
      }
    }, POLL_INTERVAL_MS);
  }

  async function handleExecute() {
    setState({ phase: "starting" });
    try {
      const record = await startExecution(plan);
      if (TERMINAL_EXECUTION_STATUSES.includes(record.status)) {
        setState({ phase: "done", record });
      } else {
        setState({ phase: "polling", record });
        schedulePoll(record.execution_id);
      }
    } catch (error) {
      const message =
        error instanceof ExecutionApiError ? error.message : "Failed to start execution.";
      setState({ phase: "error", message });
    }
  }

  async function handleCancel() {
    if (state.phase !== "polling") return;
    try {
      await cancelExecution(state.record.execution_id);
    } catch {
      // Cancellation is best-effort from the UI's perspective -- the
      // next poll tick will reflect whatever the backend actually did.
    }
  }

  const isValidPlan = plan.status !== "invalid" && plan.steps.length > 0;
  const isBusy = state.phase === "starting" || state.phase === "polling";
  const record = state.phase === "polling" || state.phase === "done" ? state.record : null;

  return (
    <section className="execution-panel" aria-label="Execution">
      <h2 className="execution-panel__title">Execution</h2>

      {!isValidPlan && (
        <p className="execution-panel__hint">
          This plan is not valid -- fix the validation issues above before executing it.
        </p>
      )}

      <div className="execution-panel__actions">
        <button
          type="button"
          className="execution-panel__button"
          onClick={handleExecute}
          disabled={!isValidPlan || isBusy}
        >
          {state.phase === "starting" ? "Starting..." : "Execute Plan"}
        </button>
        {state.phase === "polling" && (
          <button
            type="button"
            className="execution-panel__button execution-panel__button--secondary"
            onClick={handleCancel}
          >
            Cancel
          </button>
        )}
      </div>

      {state.phase === "error" && <p className="execution-panel__error">{state.message}</p>}

      {record && (
        <div className="execution-panel__result">
          <div
            className={`execution-panel__status execution-panel__status--${record.status}`}
            aria-live="polite"
          >
            Robot state: {STATUS_LABEL[record.status] ?? record.status.toUpperCase()}
          </div>

          {record.error && (
            <p className="execution-panel__error">
              ⚠ {record.error.code}: {record.error.message}
            </p>
          )}

          <h3 className="execution-panel__section-title">Current Plan</h3>
          <ExecutionStepsList steps={record.step_results} />

          <h3 className="execution-panel__section-title">Execution Log</h3>
          <ExecutionLog events={record.events} />
        </div>
      )}
    </section>
  );
}

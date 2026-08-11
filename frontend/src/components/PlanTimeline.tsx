// PlanTimeline.tsx
//
// Purpose
// -------
// Mission Control's "MILO's Plan" panel (Phase 8.6 spec section 11):
// extends `PlanStepsList`'s plain checklist with real per-step
// execution timing/retry/error data that already exists on
// `TaskState.execution_history` (`ExecutionRecord.step_results`,
// `backend/execution/models.py::StepExecutionRecord`/`ActionResult`)
// but was never rendered anywhere in the UI. Every step still shows
// its live `PlanStep.status` exactly like `PlanStepsList` (completed/
// running/pending/failed/skipped/blocked/cancelled -- set in place by
// `ExecutionController`); the timing/retry/error row only appears when
// a matching `StepExecutionRecord` exists for that step, never a
// fabricated "0ms".
import type { PlanStep, StepStatus } from "../api/plannerTypes";
import type { ExecutionRecord, StepExecutionRecord } from "../api/executionTypes";

const STATUS_ICON: Record<StepStatus, string> = {
  completed: "✓",
  running: "◐",
  pending: "○",
  failed: "✗",
  skipped: "⊘",
  blocked: "⛔",
  cancelled: "⊗",
};

function formatParameters(parameters: Record<string, unknown>): string | null {
  const entries = Object.entries(parameters);
  if (entries.length === 0) return null;
  return entries.map(([key, value]) => `${key}: ${String(value)}`).join(", ");
}

/**
 * Latest `StepExecutionRecord` for each step id, across every
 * execution attempt in `execution_history` -- a replanned task can
 * execute the same `step_id` more than once, so a later attempt's
 * result (not the first) reflects what actually happened most recently.
 */
function latestStepResults(
  executionHistory: ExecutionRecord[],
): Map<number, StepExecutionRecord> {
  const byStepId = new Map<number, StepExecutionRecord>();
  for (const record of executionHistory) {
    for (const stepResult of record.step_results) {
      byStepId.set(stepResult.step_id, stepResult);
    }
  }
  return byStepId;
}

interface PlanTimelineProps {
  steps: PlanStep[];
  executionHistory: ExecutionRecord[];
}

export function PlanTimeline({ steps, executionHistory }: PlanTimelineProps) {
  if (steps.length === 0) {
    return <p className="plan-steps__empty">No steps generated.</p>;
  }

  const stepResults = latestStepResults(executionHistory);

  return (
    <ol className="plan-steps">
      {steps.map((step) => {
        const params = formatParameters(step.parameters);
        const result = stepResults.get(step.step_id)?.result;
        return (
          <li key={step.step_id} className={`plan-steps__item plan-steps__item--${step.status}`}>
            <span className="plan-steps__icon" aria-hidden="true">
              {STATUS_ICON[step.status]}
            </span>
            <div className="plan-steps__body">
              <span className="plan-steps__description">{step.description}</span>
              {params && <span className="plan-steps__params">({params})</span>}
              {result && (
                <div className="plan-timeline__meta">
                  <span className="plan-timeline__meta-item">{Math.round(result.duration_ms)}ms</span>
                  {result.retry_count > 0 && (
                    <span className="plan-timeline__meta-item plan-timeline__meta-item--retry">
                      {result.retry_count} {result.retry_count === 1 ? "retry" : "retries"}
                    </span>
                  )}
                  {result.error && (
                    <span className="plan-timeline__meta-item plan-timeline__meta-item--error">
                      {result.error}
                    </span>
                  )}
                </div>
              )}
              {(step.preconditions.length > 0 || step.postconditions.length > 0) && (
                <details className="plan-steps__conditions">
                  <summary>Conditions</summary>
                  {step.preconditions.length > 0 && (
                    <div>
                      <strong>Requires:</strong> {step.preconditions.join("; ")}
                    </div>
                  )}
                  {step.postconditions.length > 0 && (
                    <div>
                      <strong>Guarantees:</strong> {step.postconditions.join("; ")}
                    </div>
                  )}
                </details>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

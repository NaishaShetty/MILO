// ExecutionStepsList.tsx
//
// Purpose
// -------
// Renders one execution's `StepExecutionRecord[]` as a checklist --
// the Phase 5 "Current Plan" execution view (mirrors
// `PlanStepsList.tsx`'s layout, but sourced from
// `execution.models.StepExecutionRecord`, which additionally carries
// an `ActionResult`/`ExecutionError` per step instead of just a bare
// status).
import type { StepStatus } from "../api/plannerTypes";
import type { StepExecutionRecord } from "../api/executionTypes";

const STATUS_ICON: Record<StepStatus, string> = {
  completed: "✓",
  running: "◐",
  pending: "○",
  failed: "✗",
  skipped: "⊘",
  blocked: "⛔",
  cancelled: "⊗",
};

interface ExecutionStepsListProps {
  steps: StepExecutionRecord[];
}

export function ExecutionStepsList({ steps }: ExecutionStepsListProps) {
  if (steps.length === 0) {
    return <p className="execution-steps__empty">No steps to execute.</p>;
  }

  return (
    <ol className="execution-steps">
      {steps.map((step) => (
        <li
          key={step.step_id}
          className={`execution-steps__item execution-steps__item--${step.status}`}
        >
          <span className="execution-steps__icon" aria-hidden="true">
            {STATUS_ICON[step.status]}
          </span>
          <div className="execution-steps__body">
            <span className="execution-steps__label">
              {step.action}
              {step.target ? ` ${step.target}` : ""}
            </span>
            {step.result && step.result.duration_ms > 0 && (
              <span className="execution-steps__duration">
                {Math.round(step.result.duration_ms)}ms
              </span>
            )}
            {step.error && (
              <span className="execution-steps__error">
                {step.error.code}: {step.error.message}
              </span>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

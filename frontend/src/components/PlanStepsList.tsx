// PlanStepsList.tsx
//
// Purpose
// -------
// Renders one `Plan`'s ordered `PlanStep`s as a checklist -- the
// section 16 "Current Plan" panel. Every step Phase 4 produces starts
// `StepStatus.PENDING` (this package never executes anything, see
// `backend/planner/models.py`'s docstring), so this component renders
// every non-pending status too for forward compatibility with Phase 5,
// which will update `PlanStep.status` as it actually executes a plan.
import type { PlanStep, StepStatus } from "../api/plannerTypes";

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

interface PlanStepsListProps {
  steps: PlanStep[];
}

export function PlanStepsList({ steps }: PlanStepsListProps) {
  if (steps.length === 0) {
    return <p className="plan-steps__empty">No steps generated.</p>;
  }

  return (
    <ol className="plan-steps">
      {steps.map((step) => {
        const params = formatParameters(step.parameters);
        return (
          <li key={step.step_id} className={`plan-steps__item plan-steps__item--${step.status}`}>
            <span className="plan-steps__icon" aria-hidden="true">
              {STATUS_ICON[step.status]}
            </span>
            <div className="plan-steps__body">
              <span className="plan-steps__description">{step.description}</span>
              {params && <span className="plan-steps__params">({params})</span>}
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

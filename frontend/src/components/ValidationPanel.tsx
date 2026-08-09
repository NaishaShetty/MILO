// ValidationPanel.tsx
//
// Purpose
// -------
// Renders a `ValidationResult` -- the section 16 "Validation" panel.
// Shows the overall valid/invalid banner plus every structured issue
// `PlanValidator` found (see `backend/planner/validator.py`), grouped
// by severity so an error (makes the plan invalid) reads distinctly
// from a warning (e.g. a redundant step, which does not).
import type { ValidationResult } from "../api/plannerTypes";

interface ValidationPanelProps {
  validation: ValidationResult;
}

export function ValidationPanel({ validation }: ValidationPanelProps) {
  const errors = validation.issues.filter((i) => i.severity === "error");
  const warnings = validation.issues.filter((i) => i.severity === "warning");

  return (
    <div className="validation-panel">
      <div
        className={`validation-panel__banner ${
          validation.valid ? "validation-panel__banner--valid" : "validation-panel__banner--invalid"
        }`}
      >
        {validation.valid ? "✓ Plan Valid" : "✗ Plan Invalid"}
        {validation.goal_satisfied === false && " -- goal not satisfied"}
        {validation.goal_satisfied === null && (
          <span className="validation-panel__unverifiable"> (goal completion not verifiable)</span>
        )}
      </div>

      {errors.length > 0 && (
        <ul className="validation-panel__issues validation-panel__issues--error">
          {errors.map((issue, i) => (
            <li key={i}>
              {issue.step_id != null && <strong>Step {issue.step_id}: </strong>}
              {issue.message}
            </li>
          ))}
        </ul>
      )}

      {warnings.length > 0 && (
        <ul className="validation-panel__issues validation-panel__issues--warning">
          {warnings.map((issue, i) => (
            <li key={i}>
              {issue.step_id != null && <strong>Step {issue.step_id}: </strong>}
              {issue.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

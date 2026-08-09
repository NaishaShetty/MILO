// PlannerPanel.tsx
//
// Purpose
// -------
// Top-level Phase 4 UI panel: given one `SingleTask` (the output of
// the Language panel), lets the user choose a planning strategy,
// generate a `Plan`, and see its steps, validation status, and a
// cross-strategy comparison -- section 16's full "ROBOT PLANNER"
// mock: Intent (already shown by `TaskCard`) -> Planner selector ->
// Current Plan -> Validation. This is the one place in the frontend
// that calls into `api/planner.ts`; it renders nothing on its own
// about how planning works internally, only the structured result.
//
// Why this takes a `SingleTask`, never a `ParsedInstruction`
// -----------------------------------------------------------------
// `backend/planner/` only ever plans one `SingleTask` at a time (a
// `MultiTask` is planned by iterating its `subtasks`, see
// `backend/tests/test_planner_e2e.py`) -- `App.tsx` is responsible for
// picking which `SingleTask` this panel plans for for a `MultiTask`
// result, mirroring the same "iterate subtasks yourself" contract
// `backend/planner/exceptions.py`'s `InvalidTaskError` docstring
// documents for the backend.
import { useState } from "react";
import { evaluatePlanners, PlannerApiError, planTask } from "../api/planner";
import type { EvaluateResponse, PlannerType, PlanningResult } from "../api/plannerTypes";
import type { SingleTask } from "../api/types";
import { ExecutionPanel } from "./ExecutionPanel";
import { PlanStepsList } from "./PlanStepsList";
import { PlannerComparisonTable } from "./PlannerComparisonTable";
import { ValidationPanel } from "./ValidationPanel";

const PLANNER_OPTIONS: { value: PlannerType; label: string }[] = [
  { value: "rule_based", label: "Rule Based" },
  { value: "react", label: "ReAct" },
  { value: "behavior_tree", label: "Behavior Tree" },
];

type PlanState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; result: PlanningResult }
  | { status: "error"; message: string };

type CompareState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "success"; result: EvaluateResponse }
  | { status: "error"; message: string };

interface PlannerPanelProps {
  task: SingleTask;
}

export function PlannerPanel({ task }: PlannerPanelProps) {
  const [plannerType, setPlannerType] = useState<PlannerType>("rule_based");
  const [planState, setPlanState] = useState<PlanState>({ status: "idle" });
  const [compareState, setCompareState] = useState<CompareState>({ status: "idle" });

  async function handleGeneratePlan() {
    setPlanState({ status: "loading" });
    try {
      const result = await planTask(task, plannerType);
      setPlanState({ status: "success", result });
    } catch (error) {
      const message =
        error instanceof PlannerApiError ? error.message : "Failed to generate a plan.";
      setPlanState({ status: "error", message });
    }
  }

  async function handleCompare() {
    setCompareState({ status: "loading" });
    try {
      const result = await evaluatePlanners(task);
      setCompareState({ status: "success", result });
    } catch (error) {
      const message =
        error instanceof PlannerApiError ? error.message : "Failed to evaluate planners.";
      setCompareState({ status: "error", message });
    }
  }

  return (
    <section className="planner-panel" aria-label="Planner">
      <h2 className="planner-panel__title">Planner</h2>

      <fieldset className="planner-panel__strategy" aria-label="Planning strategy">
        <legend>Strategy</legend>
        {PLANNER_OPTIONS.map((option) => (
          <label key={option.value} className="planner-panel__strategy-option">
            <input
              type="radio"
              name="planner-strategy"
              value={option.value}
              checked={plannerType === option.value}
              onChange={() => setPlannerType(option.value)}
            />
            {option.label}
          </label>
        ))}
      </fieldset>

      <div className="planner-panel__actions">
        <button
          type="button"
          className="planner-panel__button"
          onClick={handleGeneratePlan}
          disabled={planState.status === "loading"}
        >
          {planState.status === "loading" ? "Planning..." : "Generate Plan"}
        </button>
        <button
          type="button"
          className="planner-panel__button planner-panel__button--secondary"
          onClick={handleCompare}
          disabled={compareState.status === "loading"}
        >
          {compareState.status === "loading" ? "Comparing..." : "Compare Strategies"}
        </button>
      </div>

      {planState.status === "error" && (
        <p className="planner-panel__error">{planState.message}</p>
      )}

      {planState.status === "success" && (
        <div className="planner-panel__result">
          <h3 className="planner-panel__section-title">
            Current Plan
            {Boolean(planState.result.plan?.metadata.react_fallback) && (
              <span className="planner-panel__fallback-note">
                {" "}
                (ReAct unavailable -- fell back to Rule Based)
              </span>
            )}
          </h3>
          {planState.result.plan ? (
            <PlanStepsList steps={planState.result.plan.steps} />
          ) : (
            <p className="plan-steps__empty">
              No plan could be generated: {planState.result.errors.join(" ")}
            </p>
          )}

          {planState.result.validation && (
            <>
              <h3 className="planner-panel__section-title">Validation</h3>
              <ValidationPanel validation={planState.result.validation} />
            </>
          )}
        </div>
      )}

      {planState.status === "success" && planState.result.plan && (
        <ExecutionPanel plan={planState.result.plan} />
      )}

      {compareState.status === "error" && (
        <p className="planner-panel__error">{compareState.message}</p>
      )}

      {compareState.status === "success" && (
        <div className="planner-panel__result">
          <h3 className="planner-panel__section-title">Planner Comparison</h3>
          <PlannerComparisonTable metrics={compareState.result.results} />
        </div>
      )}
    </section>
  );
}

// ResultView.tsx
//
// Purpose
// -------
// Renders a successful `ParseResponse`: dispatches on
// `result.task_type` to show either a single `TaskCard` or an ordered
// list of `TaskCard`s for a `MultiTask`'s `subtasks` -- this is Phase
// 3.7's "do not assume every response is a SingleTask" requirement.
// Also shows the `ClarificationBanner` when `status ===
// "clarification_required"`, and the safe diagnostics panel when
// present. Contains no logic that inspects HTTP status codes or error
// categories -- by the time this component renders, `App.tsx` has
// already established the request succeeded.
//
// Phase 4 addition: `PlannerPanel`
// -----------------------------------
// `backend/planner/` only ever plans one `SingleTask` at a time (see
// `PlannerPanel.tsx`'s own docstring), so for a `MultiTask` result this
// component lets the user pick which subtask to plan via a simple
// selector, defaulting to the first. This is the one place the
// Language and Planner panels are visibly connected -- a task parsed
// on the left can be handed directly to the planner on the right,
// demonstrating the Phase 3 -> Phase 4 pipeline this project's README
// documents.
import { useState } from "react";
import type { ParseResponse } from "../api/types";
import { ClarificationBanner } from "./ClarificationBanner";
import { DiagnosticsPanel } from "./DiagnosticsPanel";
import { PlannerPanel } from "./PlannerPanel";
import { TaskCard } from "./TaskCard";

interface ResultViewProps {
  response: ParseResponse;
}

export function ResultView({ response }: ResultViewProps) {
  const { result } = response;
  const [selectedSubtaskIndex, setSelectedSubtaskIndex] = useState(0);

  const taskToPlan = result.task_type === "single" ? result : result.subtasks[selectedSubtaskIndex];

  return (
    <div className="result-view">
      {response.status === "clarification_required" && (
        <ClarificationBanner reason={result.clarification_reason} />
      )}

      {result.task_type === "single" ? (
        <TaskCard task={result} />
      ) : (
        <div className="result-view__subtasks">
          {result.subtasks.map((subtask, i) => (
            <TaskCard key={subtask.task_id} task={subtask} index={i + 1} />
          ))}
        </div>
      )}

      {response.diagnostics && <DiagnosticsPanel diagnostics={response.diagnostics} />}

      {result.task_type === "multi" && result.subtasks.length > 0 && (
        <label className="result-view__subtask-picker">
          Plan subtask:
          <select
            value={selectedSubtaskIndex}
            onChange={(e) => setSelectedSubtaskIndex(Number(e.target.value))}
          >
            {result.subtasks.map((subtask, i) => (
              <option key={subtask.task_id} value={i}>
                Task {i + 1}: {subtask.goal ?? "(no goal)"}
              </option>
            ))}
          </select>
        </label>
      )}

      {taskToPlan && !taskToPlan.needs_clarification && <PlannerPanel task={taskToPlan} />}
    </div>
  );
}

// PlannerComparisonTable.tsx
//
// Purpose
// -------
// Renders the section 17 "planner comparison" dashboard: one row per
// strategy with real, freshly measured metrics from
// `POST /api/v1/planner/evaluate` (`backend/planner/evaluation.py`).
// Never fabricates a number -- a strategy that has not been evaluated
// yet simply is not in `metrics`, and this component never invents a
// placeholder value for one that is.
import type { PlannerMetrics } from "../api/plannerTypes";

interface PlannerComparisonTableProps {
  metrics: PlannerMetrics[];
}

const LABELS: Record<string, string> = {
  rule_based: "Rule Based",
  react: "ReAct",
  behavior_tree: "Behavior Tree",
};

export function PlannerComparisonTable({ metrics }: PlannerComparisonTableProps) {
  if (metrics.length === 0) {
    return <p className="planner-comparison__empty">Not evaluated yet.</p>;
  }

  return (
    <table className="planner-comparison">
      <thead>
        <tr>
          <th>Planner</th>
          <th>Steps</th>
          <th>Valid</th>
          <th>Goal Met</th>
          <th>Latency</th>
        </tr>
      </thead>
      <tbody>
        {metrics.map((m) => (
          <tr key={m.planner_type}>
            <td>{LABELS[m.planner_type] ?? m.planner_type}</td>
            <td>{m.success ? m.step_count : "--"}</td>
            <td className={m.valid ? "planner-comparison__ok" : "planner-comparison__fail"}>
              {m.valid ? "✓" : "✗"}
            </td>
            <td>
              {m.goal_satisfied === null || m.goal_satisfied === undefined
                ? "n/a"
                : m.goal_satisfied
                  ? "✓"
                  : "✗"}
            </td>
            <td>{m.latency_ms.toFixed(2)} ms</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

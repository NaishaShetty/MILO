// PlannerPicker.tsx -- choose how MILO plans (sent as `planner` on task creation).
import type { PlannerChoice } from "../api/tasksTypes";

export const PLANNER_OPTIONS: Array<{ value: PlannerChoice; label: string; hint: string }> = [
  { value: "rule_based", label: "Steady", hint: "Rule-based: fast and predictable." },
  { value: "react", label: "Thinker", hint: "Asks a language model; falls back to Steady without one." },
  { value: "behavior_tree", label: "Branching", hint: "Behavior tree: plans with fallbacks." },
  { value: "htn", label: "Step-by-step", hint: "HTN: breaks big jobs into smaller ones." },
];

export interface PlannerPickerProps {
  value: PlannerChoice;
  onChange: (value: PlannerChoice) => void;
  disabled?: boolean;
}

export function PlannerPicker({ value, onChange, disabled }: PlannerPickerProps) {
  const current = PLANNER_OPTIONS.find((o) => o.value === value);
  return (
    <label className="muted" style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
      How should MILO plan?
      <select
        className="select"
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as PlannerChoice)}
        title={current?.hint}
      >
        {PLANNER_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

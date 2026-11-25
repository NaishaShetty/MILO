// PlannerPicker.tsx -- choose how MILO plans (sent as `planner` on task creation).
import type { PlannerChoice } from "../api/tasksTypes";

import { PLANNER_OPTIONS } from "./plannerOptions";

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

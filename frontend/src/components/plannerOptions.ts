// plannerOptions.ts -- the planners a user can pick, with plain-language labels.
import type { PlannerChoice } from "../api/tasksTypes";

export const PLANNER_OPTIONS: Array<{ value: PlannerChoice; label: string; hint: string }> = [
  { value: "rule_based", label: "Steady", hint: "Rule-based: fast and predictable." },
  { value: "react", label: "Thinker", hint: "Asks a language model; falls back to Steady without one." },
  { value: "behavior_tree", label: "Branching", hint: "Behavior tree: plans with fallbacks." },
  { value: "htn", label: "Step-by-step", hint: "HTN: breaks big jobs into smaller ones." },
];

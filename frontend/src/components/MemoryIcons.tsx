// MemoryIcons.tsx
//
// Purpose
// -------
// Inline-SVG icon set for the Memory page (spec: no emoji UI icons).
// One icon per real `MemoryType` (`api/memoryTypes.ts`) plus an "all"
// icon for the unfiltered tab and the page's toolbar glyphs (search,
// refresh, chevron, task, clock). Purely decorative -- keyed off the
// same `MemoryType` strings the real filter/count logic already uses.
import type { StatusPillTone } from "./StatusPill";

export type MemoryIconName =
  | "all"
  | "semantic"
  | "episodic"
  | "failure"
  | "user"
  | "search"
  | "refresh"
  | "chevron"
  | "task"
  | "clock";

const PATHS: Record<MemoryIconName, string> = {
  // Stacked layers -- "All".
  all: "M8 2.3 13.7 5.2 8 8.1 2.3 5.2 8 2.3Z M2.3 8l5.7 2.9L13.7 8 M2.3 10.8l5.7 2.9 5.7-2.9",
  // Network/node -- "Semantic" (persistent knowledge).
  semantic: "M8 3.2v3 M8 9.8v3 M4 5.5l3 2 M9 7.5l3-2 M4 10.5l3-2 M9 8.5l3 2 M8 3.2a1.2 1.2 0 1 0 0-2.4 1.2 1.2 0 0 0 0 2.4Z M3.2 5.9a1.2 1.2 0 1 0 0-2.4 1.2 1.2 0 0 0 0 2.4Z M12.8 5.9a1.2 1.2 0 1 0 0-2.4 1.2 1.2 0 0 0 0 2.4Z M8 13.2a1.2 1.2 0 1 0 0-2.4 1.2 1.2 0 0 0 0 2.4Z M3.2 10.5a1.2 1.2 0 1 0 0-2.4 1.2 1.2 0 0 0 0 2.4Z M12.8 10.5a1.2 1.2 0 1 0 0-2.4 1.2 1.2 0 0 0 0 2.4Z",
  // Clock/history -- "Episodic" (experiences over time).
  episodic: "M8 4.2v4l2.6 1.5 M8 2.2a5.8 5.8 0 1 1 0 11.6 5.8 5.8 0 0 1 0-11.6Z",
  // Warning triangle -- "Failure".
  failure: "M8 2.6 14 13H2L8 2.6Z M8 6.6v2.8 M8 11.1v.1",
  // Person -- "User".
  user: "M8 8.2A2.6 2.6 0 1 0 8 3a2.6 2.6 0 0 0 0 5.2Z M3 13.4c.6-2.6 2.5-4 5-4s4.4 1.4 5 4",
  search: "M7 12.2A5.2 5.2 0 1 0 7 1.8a5.2 5.2 0 0 0 0 10.4Z M11 11l3.5 3.5",
  refresh: "M12.8 8A4.8 4.8 0 1 1 11 4.4 M12.8 3v3.4h-3.4",
  chevron: "M6 3.5 10.5 8 6 12.5",
  task: "M4 5.5h8v6.5H4V5.5Z M6 5.5V4a2 2 0 0 1 4 0v1.5",
  clock: "M8 4.2v4l2.6 1.5 M8 2.2a5.8 5.8 0 1 1 0 11.6 5.8 5.8 0 0 1 0-11.6Z",
};

/** Real `MemoryType` -> the accent `StatusPillTone` used for that
 * category's icon/label/border throughout the page (spec section 14). */
export const MEMORY_CATEGORY_TONE: Record<string, StatusPillTone> = {
  all: "accent",
  semantic: "info",
  episodic: "accent",
  failure: "warning",
  user: "success",
};

export interface MemoryIconProps {
  name: MemoryIconName;
  className?: string;
}

export function MemoryIcon({ name, className }: MemoryIconProps) {
  const classes = ["memory-icon", className].filter(Boolean).join(" ");
  return (
    <svg
      className={classes}
      width="15"
      height="15"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.15"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

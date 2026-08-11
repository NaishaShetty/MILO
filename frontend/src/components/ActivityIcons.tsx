// ActivityIcons.tsx
//
// Purpose
// -------
// Inline-SVG icon set for the Activity page (spec: no emoji, no
// generic browser controls) -- one icon per real `ACTIVITY_CATEGORIES`
// entry (`utils/activity.ts`) plus the toolbar/header glyphs (search,
// export, calendar, clock). Purely decorative/presentational: icons
// are keyed off the same category `id`s the real filter/count logic
// already uses, never a new data source.
import type { StatusPillTone } from "./StatusPill";

export type ActivityIconName =
  | "all"
  | "tasks"
  | "perception"
  | "planning"
  | "execution"
  | "memory"
  | "reflection"
  | "errors"
  | "search"
  | "download"
  | "calendar"
  | "task-link";

const PATHS: Record<ActivityIconName, string> = {
  // Clock/history -- "All Events".
  all: "M8 3.5v4.7l3.2 1.9 M8 2.2a5.8 5.8 0 1 1 0 11.6 5.8 5.8 0 0 1 0-11.6Z",
  // Check inside a shield -- "Tasks".
  tasks: "M8 2.3 12.8 4v3.6c0 3-2 5.4-4.8 6.1-2.8-.7-4.8-3.1-4.8-6.1V4L8 2.3Z M6 8.1l1.4 1.4L10.2 6.7",
  // Eye -- "Perception".
  perception: "M1.5 8S3.8 4 8 4s6.5 4 6.5 4-2.3 4-6.5 4-6.5-4-6.5-4Z M8 9.8A1.8 1.8 0 1 0 8 6.2a1.8 1.8 0 0 0 0 3.6Z",
  // Brain -- "Planning".
  planning:
    "M6.3 2.6a1.9 1.9 0 0 0-1.9 1.9v.2a1.7 1.7 0 0 0-1 2.9 1.8 1.8 0 0 0 .7 3.2 1.9 1.9 0 0 0 2.2 2h1V2.6h-1Z M9.7 2.6a1.9 1.9 0 0 1 1.9 1.9v.2a1.7 1.7 0 0 1 1 2.9 1.8 1.8 0 0 1-.7 3.2 1.9 1.9 0 0 1-2.2 2h-1V2.6h1Z",
  // Command/plug -- "Execution".
  execution: "M6.2 2.5v2.3 M9.8 2.5v2.3 M3.6 6.3h8.8v2.1a4.4 4.4 0 0 1-4.4 4.4 4.4 4.4 0 0 1-4.4-4.4V6.3Z M6.2 12.8v.9 M9.8 12.8v.9",
  // Stacked disks -- "Memory".
  memory:
    "M8 3.2c2.7 0 4.8.8 4.8 1.8S10.7 6.8 8 6.8 3.2 6 3.2 5s2.1-1.8 4.8-1.8Z M3.2 5v3c0 1 2.1 1.8 4.8 1.8s4.8-.8 4.8-1.8V5 M3.2 8v3c0 1 2.1 1.8 4.8 1.8s4.8-.8 4.8-1.8V8",
  // Sparkles -- "Reflection".
  reflection:
    "M7 2.6 7.9 5l2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9.9-2.4Z M12 9.4l.5 1.3 1.3.5-1.3.5-.5 1.3-.5-1.3-1.3-.5 1.3-.5.5-1.3Z",
  // Warning triangle -- "Errors".
  errors: "M8 2.6 14 13H2L8 2.6Z M8 6.6v2.8 M8 11.1v.1",
  search: "M7 12.2A5.2 5.2 0 1 0 7 1.8a5.2 5.2 0 0 0 0 10.4Z M11 11l3.5 3.5",
  download: "M8 2.5v7.4 M4.8 7.1 8 10.3l3.2-3.2 M3 12.8h10",
  calendar: "M3 4h10v9.5H3V4Z M3 6.6h10 M5.6 2.3v2.6 M10.4 2.3v2.6",
  "task-link": "M4 5.5h8v6.5H4V5.5Z M6 5.5V4a2 2 0 0 1 4 0v1.5",
};

const STROKE_ICONS = new Set<ActivityIconName>(["search", "download", "calendar", "task-link"]);

/** Real category `id` (`ACTIVITY_CATEGORIES`) -> the accent `StatusPillTone` the
 * spec assigns it (section 9). Kept alongside the icon map since both are the
 * same "how do we present this real category" decision. */
export const ACTIVITY_CATEGORY_TONE: Record<string, StatusPillTone> = {
  all: "accent",
  tasks: "success",
  perception: "info",
  planning: "success",
  execution: "accent",
  memory: "accent",
  reflection: "accent",
  errors: "danger",
};

export interface ActivityIconProps {
  name: ActivityIconName;
  className?: string;
}

export function ActivityIcon({ name, className }: ActivityIconProps) {
  const classes = ["activity-icon", className].filter(Boolean).join(" ");
  const isStrokeOnly = STROKE_ICONS.has(name);
  return (
    <svg
      className={classes}
      width="15"
      height="15"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth={isStrokeOnly ? 1.3 : 1.1}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

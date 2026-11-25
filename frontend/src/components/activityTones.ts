// activityTones.ts -- which StatusPill tone each Activity category uses.
import type { StatusPillTone } from "./StatusPill";

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

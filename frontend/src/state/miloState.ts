// miloState.ts
//
// Purpose
// -------
// The ONE canonical MILO state type (Phase 8.3 visual foundation).
// Every page/component that needs to know "what is MILO doing right
// now" imports `MiloState` from here and reads it from
// `MiloStateContext` (see `MiloStateContext.tsx`) instead of deriving
// its own local notion of state -- this file is what makes that
// possible without a circular import between the context and the
// avatar component that renders it.
//
// Visual asset mapping
// ---------------------
// The MOCKUPS/MILO reference directory supplies exactly eight
// character images (idle/listening/thinking/speaking/executing/
// success/error, plus the neutral "reference" pose). The application
// state machine below is finer-grained than that -- e.g. "planning",
// "replanning", and "reflecting" are all real, distinct backend task
// statuses -- so `VISUAL_FOR_STATE` maps each logical state to
// whichever *supplied* reference image communicates it best. This is
// an explicit, one-time mapping decision (not a per-page guess): any
// new logical state added later must be given an entry here rather
// than left to fall through.
export type MiloState =
  | "offline"
  | "initializing"
  | "idle"
  | "listening"
  | "understanding"
  | "thinking"
  | "planning"
  | "perceiving"
  | "navigating"
  | "executing"
  | "replanning"
  | "reflecting"
  | "speaking"
  | "success"
  | "error";

/** The eight real asset files under /assets/milo/ (Phase 8.3). */
export type MiloVisual =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "executing"
  | "success"
  | "error";

export const MILO_ASSET_SRC: Record<MiloVisual, string> = {
  idle: "/assets/milo/milo-idle.png",
  listening: "/assets/milo/milo-listening.png",
  thinking: "/assets/milo/milo-thinking.png",
  speaking: "/assets/milo/milo-speaking.png",
  executing: "/assets/milo/milo-executing.png",
  success: "/assets/milo/milo-success.png",
  error: "/assets/milo/milo-error.png",
};

// Logical state -> which of the eight supplied reference images best
// communicates it. "offline" also renders the idle pose (dimmed via
// CSS -- see MiloAvatar.css rules -- rather than a nonexistent ninth
// asset).
export const VISUAL_FOR_STATE: Record<MiloState, MiloVisual> = {
  offline: "idle",
  initializing: "idle",
  idle: "idle",
  listening: "listening",
  understanding: "thinking",
  thinking: "thinking",
  planning: "thinking",
  perceiving: "idle",
  navigating: "executing",
  executing: "executing",
  replanning: "thinking",
  reflecting: "thinking",
  speaking: "speaking",
  success: "success",
  error: "error",
};

export const MILO_STATE_LABELS: Record<MiloState, string> = {
  offline: "MILO is offline",
  initializing: "MILO is waking up",
  idle: "MILO is ready",
  listening: "MILO is listening",
  understanding: "MILO is understanding",
  thinking: "MILO is thinking",
  planning: "MILO is planning",
  perceiving: "MILO is looking",
  navigating: "MILO is navigating",
  executing: "MILO is acting",
  replanning: "MILO is replanning",
  reflecting: "MILO is reflecting",
  speaking: "MILO is speaking",
  success: "MILO succeeded",
  error: "MILO ran into a problem",
};

export const MILO_STATE_DESCRIPTIONS: Record<MiloState, string> = {
  offline: "Waiting for the backend to come online.",
  initializing: "Getting ready to help.",
  idle: "Waiting for an instruction.",
  listening: "Listening to your instruction.",
  understanding: "Turning what you said into a goal.",
  thinking: "Recalling what might help.",
  planning: "Breaking the goal into steps.",
  perceiving: "Looking at the current scene.",
  navigating: "Moving through the environment.",
  executing: "Carrying out the current step.",
  replanning: "Something changed -- adjusting the plan.",
  reflecting: "Reviewing what just happened.",
  speaking: "Responding out loud.",
  success: "Mission complete.",
  error: "Something went wrong.",
};

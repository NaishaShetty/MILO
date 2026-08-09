// MiloCharacter.tsx
//
// Purpose
// -------
// The MILO character -- an original SVG/CSS illustration (hoodie
// silhouette, glowing eyes, purple rim-light), not a copy of the
// MOCKUPS reference art (those files are never imported/bundled --
// see the Phase 8.2 plan's MOCKUPS handling). Renders one of a fixed
// set of real, backend-derived states (spec section 13/14) -- callers
// are responsible for deriving `state` from real TaskStatus/
// AgentStateValue/voice-state, never choosing it arbitrarily. See
// each page's own state-derivation comment (added in Stage 3) for
// exactly which real fields feed this prop on that page.
export type MiloCharacterState =
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

export interface MiloCharacterProps {
  state: MiloCharacterState;
  /** "sm" for compact contexts (nav avatar), "lg" for a hero placement. */
  size?: "sm" | "md" | "lg";
}

const STATE_LABELS: Record<MiloCharacterState, string> = {
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

export function MiloCharacter({ state, size = "md" }: MiloCharacterProps) {
  return (
    <div
      className={`milo-character milo-character--${size} milo-character--${state}`}
      role="img"
      aria-label={STATE_LABELS[state]}
    >
      <div className="milo-character__glow" aria-hidden="true" />
      <svg
        className="milo-character__svg"
        viewBox="0 0 120 140"
        fill="none"
        aria-hidden="true"
      >
        <ellipse
          className="milo-character__shadow"
          cx="60"
          cy="132"
          rx="34"
          ry="6"
        />
        <path
          className="milo-character__body"
          d="M28 138 L26 92 C26 60 40 42 60 42 C80 42 94 60 94 92 L92 138 Z"
        />
        <path
          className="milo-character__hood"
          d="M60 8 C34 8 20 30 20 58 C20 78 30 90 44 96 C36 84 34 66 40 54 C46 42 54 36 60 36 C66 36 74 42 80 54 C86 66 84 84 76 96 C90 90 100 78 100 58 C100 30 86 8 60 8 Z"
        />
        <rect
          className="milo-character__eye milo-character__eye--left"
          x="46"
          y="56"
          width="8"
          height="18"
          rx="4"
        />
        <rect
          className="milo-character__eye milo-character__eye--right"
          x="66"
          y="56"
          width="8"
          height="18"
          rx="4"
        />
      </svg>
    </div>
  );
}

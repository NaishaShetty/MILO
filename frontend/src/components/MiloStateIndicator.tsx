// MiloStateIndicator.tsx
//
// Purpose
// -------
// Small text readout of MILO's current canonical state -- the
// Mission Control mockup's "MILO STATUS" card ("Navigating" / "Moving
// to the dining table to locate the mug.") pairs a state title with a
// one-line description next to the avatar; this component is that
// pairing, reusable anywhere the app shows MILO's state as text
// rather than (or alongside) the avatar image itself.
import { MILO_STATE_DESCRIPTIONS, MILO_STATE_LABELS } from "../state/miloState";
import type { MiloState } from "../state/miloState";

export interface MiloStateIndicatorProps {
  state: MiloState;
  className?: string;
}

// "MILO is navigating" -> "Navigating" for the title; the label map
// stays sentence-form because it also serves as each avatar's alt
// text (MiloAvatar.tsx). `error`/`success` are checked first --
// stripping "MILO succeeded"'s prefix leaves an empty label (the
// whole string matches the strip pattern), which used to fall through
// to the generic "empty label -> Ready" branch below and never reach
// the "Success" override at all -- a real bug an E2E test caught by
// asserting on the actual rendered title text, not just the
// underlying `MiloState` value (Phase 8.5).
function titleFor(state: MiloState): string {
  if (state === "error") return "Error";
  if (state === "success") return "Success";
  const label = MILO_STATE_LABELS[state].replace(/^MILO (is|ran into|succeeded)/i, "").trim();
  return label ? label.charAt(0).toUpperCase() + label.slice(1) : "Ready";
}

export function MiloStateIndicator({ state, className }: MiloStateIndicatorProps) {
  const classes = ["milo-state-indicator", `milo-state-indicator--${state}`, className]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={classes}>
      <span className="milo-state-indicator__title">{titleFor(state)}</span>
      <span className="milo-state-indicator__description">{MILO_STATE_DESCRIPTIONS[state]}</span>
    </div>
  );
}

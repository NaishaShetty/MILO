// MiloPresence.tsx
//
// Purpose
// -------
// Composite "MILO is here" placement used by hero sections (Home,
// About MILO) that show the avatar together with whatever it's
// currently saying -- pairs `MiloAvatar` with `MiloDialogue` so pages
// don't each re-implement the same avatar+bubble layout/positioning.
import { MiloAvatar } from "./MiloAvatar";
import { MiloDialogue } from "./MiloDialogue";
import type { MiloState } from "../state/miloState";

export interface MiloPresenceProps {
  state: MiloState;
  size?: "sm" | "md" | "lg";
  dialogueText?: string;
  dialogueCaption?: string;
  className?: string;
}

export function MiloPresence({
  state,
  size = "lg",
  dialogueText,
  dialogueCaption,
  className,
}: MiloPresenceProps) {
  const classes = ["milo-presence", className].filter(Boolean).join(" ");
  return (
    <div className={classes}>
      <MiloAvatar state={state} size={size} />
      {dialogueText && (
        <MiloDialogue text={dialogueText} caption={dialogueCaption} className="milo-presence__dialogue" />
      )}
    </div>
  );
}

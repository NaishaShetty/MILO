// MiloAvatar.tsx -- the app-wide MILO figure: the layered SVG robot, with
// the pose chosen from the real MILO state (never a timer).
import type { MiloState } from "../state/miloState";
import { MILO_STATE_LABELS } from "../state/miloState";
import { MiloRobot, poseForState } from "./MiloRobot";

export interface MiloAvatarProps {
  state: MiloState;
  /** "sm" for compact contexts (nav avatar), "md" default, "lg" for a hero placement. */
  size?: "sm" | "md" | "lg";
  className?: string;
}

const PIXELS = { sm: 44, md: 120, lg: 220 } as const;

export function MiloAvatar({ state, size = "md", className }: MiloAvatarProps) {
  const classes = ["milo-avatar", `milo-avatar--${size}`, `milo-avatar--state-${state}`, className]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={classes} title={MILO_STATE_LABELS[state]}>
      <MiloRobot pose={poseForState(state)} size={PIXELS[size]} />
    </div>
  );
}

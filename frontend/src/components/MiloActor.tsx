// MiloActor.tsx -- MILO free-standing on the page (no box), positioned from a
// `MiloDirection`. `x` is a 0..1 position within the parent; `null` = home.
import type { MiloDirection } from "../state/miloDirector";
import { MiloRobot } from "./MiloRobot";

export interface MiloActorProps {
  direction: MiloDirection;
  size?: number;
  /** Where "home" is, as a fraction of the parent's width. */
  homeX?: number;
  paused?: boolean;
}

export function MiloActor({ direction, size = 120, homeX = 0.1, paused }: MiloActorProps) {
  const x = direction.x ?? homeX;
  return (
    <div className="milo-actor" style={{ left: `${x * 100}%`, width: size }} data-testid="milo-actor">
      <MiloRobot
        pose={direction.pose}
        facing={direction.facing}
        carrying={direction.carrying}
        size={size}
        paused={paused}
      />
    </div>
  );
}

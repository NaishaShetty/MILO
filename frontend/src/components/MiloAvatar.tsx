// MiloAvatar.tsx
//
// Purpose
// -------
// Renders MILO using the real, canonical character artwork supplied
// in MOCKUPS/MILO -- copied verbatim into /public/assets/milo/ (Phase
// 8.3; see that directory's own note) -- never a redrawn SVG/stock
// substitute. Callers pass a real `MiloState` (from
// `MiloStateContext`, or an explicit prop where a page legitimately
// needs to show a specific state outside the live app, e.g. a design
// preview); this component owns exactly one thing: picking the right
// reference image for that state (`VISUAL_FOR_STATE`, `miloState.ts`)
// and layering restrained CSS motion on top of it. The reference
// image defines what MILO *looks like* in each state; the CSS here
// only adds motion around it -- it never swaps in a different
// character or invents a visual variant the mockups didn't supply.
import { MILO_ASSET_SRC, MILO_STATE_LABELS, VISUAL_FOR_STATE } from "../state/miloState";
import type { MiloState } from "../state/miloState";

export interface MiloAvatarProps {
  state: MiloState;
  /** "sm" for compact contexts (nav avatar), "md" default, "lg" for a hero placement. */
  size?: "sm" | "md" | "lg";
  className?: string;
}

export function MiloAvatar({ state, size = "md", className }: MiloAvatarProps) {
  const visual = VISUAL_FOR_STATE[state];
  const classes = [
    "milo-avatar",
    `milo-avatar--${size}`,
    `milo-avatar--visual-${visual}`,
    `milo-avatar--state-${state}`,
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={classes}>
      <div className="milo-avatar__glow" aria-hidden="true" />
      {/* The supplied reference art is a flat render with its own dark
       * vignette baked in (no alpha channel -- see miloState.ts's own
       * note); this backdrop is color-matched to that baked-in tone and
       * blurred well past any hard edge so `.milo-avatar__image`'s mask
       * fade reveals *this* instead of jumping straight to whatever
       * page background sits behind it -- the seam disappears because
       * both sides of the fade are (almost) the same color. */}
      <div className="milo-avatar__art-glow" aria-hidden="true" />
      <img
        className="milo-avatar__image"
        src={MILO_ASSET_SRC[visual]}
        alt={MILO_STATE_LABELS[state]}
        draggable={false}
      />
    </div>
  );
}

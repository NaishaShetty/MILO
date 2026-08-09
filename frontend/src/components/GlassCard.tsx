// GlassCard.tsx
//
// Purpose
// -------
// The translucent-bordered card shell every Phase 8.2 page panel uses
// (see MOCKUPS -- every "MILO'S EYES" / "CURRENT MISSION" / "MY
// KNOWLEDGE" style panel is this same shell around different content).
// A pure layout/visual wrapper -- never fetches data, never knows what
// it contains.
import type { ReactNode } from "react";

export interface GlassCardProps {
  children: ReactNode;
  className?: string;
  /** Optional small heading rendered above `children`, matching the
   * mockups' "ICON LABEL" card-title row. Prefer `SectionHeader` for
   * a page-level heading; this is for a card-level one. */
  title?: ReactNode;
  /** Right-aligned slot next to `title` (e.g. "View All ->", a count). */
  titleAction?: ReactNode;
}

export function GlassCard({ children, className, title, titleAction }: GlassCardProps) {
  const classes = ["glass-card", className].filter(Boolean).join(" ");
  return (
    <div className={classes}>
      {(title || titleAction) && (
        <div className="glass-card__header">
          {title && <h3 className="glass-card__title">{title}</h3>}
          {titleAction && <div className="glass-card__title-action">{titleAction}</div>}
        </div>
      )}
      <div className="glass-card__body">{children}</div>
    </div>
  );
}

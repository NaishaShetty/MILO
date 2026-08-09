// StatusPill.tsx
//
// Purpose
// -------
// A small rounded status/label chip -- the visual primitive behind
// "MILO is Ready", agent state badges, activity-category filters, and
// experiment status ("Success"/"Partial"/"Running"). `tone` maps to
// this project's semantic color set (spec section 10); callers choose
// `tone` from real state, this component never invents which tone a
// given real status deserves on its own.
import type { ReactNode } from "react";

export type StatusPillTone = "neutral" | "accent" | "success" | "danger" | "warning" | "info";

export interface StatusPillProps {
  children: ReactNode;
  tone?: StatusPillTone;
  /** Renders a small leading dot (e.g. the "MILO is Ready" green dot). */
  dot?: boolean;
  className?: string;
}

export function StatusPill({ children, tone = "neutral", dot = false, className }: StatusPillProps) {
  const classes = ["status-pill", `status-pill--${tone}`, className].filter(Boolean).join(" ");
  return (
    <span className={classes}>
      {dot && <span className="status-pill__dot" aria-hidden="true" />}
      {children}
    </span>
  );
}

// SectionHeader.tsx
//
// Purpose
// -------
// The large page-level heading block used at the top of every Phase
// 8.2 page (e.g. Home's "Hi, I'm MILO.", Memory's "I remember, so I
// can do better.") -- title, optional purple-emphasized fragment,
// optional subtitle/description, optional right-aligned action slot.
import type { ReactNode } from "react";

export interface SectionHeaderProps {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function SectionHeader({
  eyebrow,
  title,
  description,
  action,
  className,
}: SectionHeaderProps) {
  const classes = ["section-header", className].filter(Boolean).join(" ");
  return (
    <div className={classes}>
      <div className="section-header__text">
        {eyebrow && <p className="section-header__eyebrow">{eyebrow}</p>}
        <h1 className="section-header__title">{title}</h1>
        {description && <p className="section-header__description">{description}</p>}
      </div>
      {action && <div className="section-header__action">{action}</div>}
    </div>
  );
}

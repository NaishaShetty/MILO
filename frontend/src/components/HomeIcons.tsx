// HomeIcons.tsx
//
// Purpose
// -------
// Small inline-SVG icon set for the Home page's illustrative example
// copy (the hero "you can ask me things like" panel and the bottom
// "try saying something" chips) -- replaces the earlier emoji glyphs,
// which render inconsistently across platforms and read as generic
// system icons rather than part of MILO's own interface. Purely
// decorative: every icon here is keyed off a fixed example string this
// page already renders, never derived from backend data.
export type HomeIconName = "mug" | "apple" | "bottle" | "question";

const PATHS: Record<HomeIconName, string> = {
  mug: "M4 4.5h9v7a3.5 3.5 0 0 1-3.5 3.5h-2A3.5 3.5 0 0 1 4 11.5v-7Z M13 6.5h1.25a2 2 0 0 1 0 4H13",
  apple:
    "M11.2 5.4c1.6-1.3 3.4-.6 3.4 1.7 0 3-2.1 6.4-4.1 6.4-.8 0-1-.4-1.5-.4s-.7.4-1.5.4c-2 0-4.1-3.4-4.1-6.4 0-2.3 1.7-3.2 3.3-2 .5.4 1 .6 1.3.6.3 0 .8-.2 1.3-.6 .3-.2.6-.4.9-.7Z M9.6 4.6c.3-.9 1-1.6 1.9-1.8",
  bottle:
    "M7 2.5h2v2.1c1 .5 1.5 1.3 1.5 2.4v5.5A1.5 1.5 0 0 1 9 14H7a1.5 1.5 0 0 1-1.5-1.5V7c0-1.1.5-1.9 1.5-2.4V2.5Z M6.2 8.5h3.6",
  question:
    "M8 14.2a.6.6 0 1 0 0-1.2.6.6 0 0 0 0 1.2Z M5.8 6.3a2.2 2.2 0 1 1 3.3 1.9c-.7.4-1.1.9-1.1 1.6v.4",
};

export interface HomeIconProps {
  name: HomeIconName;
  className?: string;
}

export function HomeIcon({ name, className }: HomeIconProps) {
  const classes = ["home-icon", className].filter(Boolean).join(" ");
  return (
    <svg
      className={classes}
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

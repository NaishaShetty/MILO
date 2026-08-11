// AboutIcons.tsx
//
// Purpose
// -------
// Small inline-SVG icon set for the About MILO page's pipeline/capability
// cards -- one icon per real pipeline stage (`AboutPage.tsx`'s
// `PIPELINE_STAGES`), replacing the numeric-index-only treatment with a
// proper UI icon per the design system's "no emoji as interface icons"
// rule. Purely decorative: keyed off the same fixed stage names the page
// already renders, never derived from backend data.
export type AboutIconName =
  | "perceive"
  | "understand"
  | "remember"
  | "plan"
  | "navigate"
  | "act"
  | "reflect"
  | "replan"
  | "learn";

const PATHS: Record<AboutIconName, string> = {
  perceive: "M1 8s2.8-4.5 7-4.5S15 8 15 8s-2.8 4.5-7 4.5S1 8 1 8Z M8 10a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z",
  understand: "M2 3h12v7H6.5L3.5 13V10H2V3Z M4.5 6h7 M4.5 8h4.5",
  remember: "M2.5 4.2c0-1 2.5-1.7 5.5-1.7s5.5.7 5.5 1.7-2.5 1.8-5.5 1.8-5.5-.8-5.5-1.8Z M2.5 4.2V11.8c0 1 2.5 1.7 5.5 1.7s5.5-.7 5.5-1.7V4.2 M2.5 8c0 1 2.5 1.8 5.5 1.8s5.5-.8 5.5-1.8",
  plan: "M3 12.5 8 3.5l5 9 M8 3.5v9 M5 12.5h6",
  navigate: "M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13Z M10.2 5.8 6.7 7.4l-1.6 3.5 3.5-1.6Z",
  act: "M4.5 2.5v11l8-5.5-8-5.5Z",
  reflect: "M8 2v1.6 M8 12.4V14 M2 8h1.6 M12.4 8H14 M4.1 4.1l1.1 1.1 M10.8 10.8l1.1 1.1 M4.1 11.9l1.1-1.1 M10.8 5.2l1.1-1.1 M8 5.5A2.5 2.5 0 1 0 8 10.5 2.5 2.5 0 0 0 8 5.5Z",
  replan: "M12.8 6.3A5 5 0 1 1 11 3.3 M12.8 2v3.3h-3.3",
  learn: "M8 3 1 6.2 8 9.4l7-3.2L8 3Z M4 8v3.3c0 .9 1.8 2.2 4 2.2s4-1.3 4-2.2V8",
};

export interface AboutIconProps {
  name: AboutIconName;
  className?: string;
}

export function AboutIcon({ name, className }: AboutIconProps) {
  const classes = ["about-icon", className].filter(Boolean).join(" ");
  return (
    <svg
      className={classes}
      width="20"
      height="20"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.1"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

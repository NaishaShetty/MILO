// LabIcons.tsx
//
// Purpose
// -------
// Inline-SVG icon set for the MILO Lab page (spec: no emoji UI icons).
// Purely decorative -- every icon here is keyed off a fixed slot in
// the page's own layout (hero action cards, Quick Start rows, Lab
// Stats tiles, the bottom CTA), never derived from backend data.
export type LabIconName =
  | "flask"
  | "code"
  | "chart"
  | "chat"
  | "cube"
  | "sliders"
  | "target"
  | "lightning"
  | "memory"
  | "lightbulb"
  | "arrow-right"
  | "plus"
  | "reset";

const PATHS: Record<LabIconName, string> = {
  flask: "M6.5 2h3 M7.2 2v3.6l-3 5.4a1.6 1.6 0 0 0 1.4 2.4h5l0 0a1.6 1.6 0 0 0 1.4-2.4l-3-5.4V2 M5.5 8.4h5",
  code: "M5.3 4.8 2 8l3.3 3.2 M10.7 4.8 14 8l-3.3 3.2 M9 3.2 7 12.8",
  chart: "M2.5 13.5h11 M4.5 13.5V9 M8 13.5V5.5 M11.5 13.5V7.5",
  chat: "M2.5 3.5h11v7h-6.2L4.5 12.8V10.5H2.5V3.5Z",
  cube: "M8 2.3 13.5 5.4v5.2L8 13.7 2.5 10.6V5.4L8 2.3Z M8 2.3v11.4 M2.5 5.4 8 8.6l5.5-3.2",
  sliders: "M3 5h10 M3 9h10 M3 13h10 M5.5 3.3v3.4 M9.8 7.3v3.4 M6.8 11.3v3.4",
  target: "M8 13.5A5.5 5.5 0 1 0 8 2.5a5.5 5.5 0 0 0 0 11Z M8 10.7A2.7 2.7 0 1 0 8 5.3a2.7 2.7 0 0 0 0 5.4Z M8 8.4l3.6-3.6",
  lightning: "M8.6 2 4 9h3.2l-.8 5L12 7H8.8l1-5-1.2 0Z",
  memory:
    "M3.2 5c0-1 2.1-1.8 4.8-1.8S12.8 4 12.8 5 10.7 6.8 8 6.8 3.2 6 3.2 5Z M3.2 5v3c0 1 2.1 1.8 4.8 1.8s4.8-.8 4.8-1.8V5 M3.2 8v3c0 1 2.1 1.8 4.8 1.8s4.8-.8 4.8-1.8V8",
  lightbulb: "M8 2.5a4 4 0 0 1 2.3 7.3c-.4.3-.7.9-.7 1.4v.3h-3.2v-.3c0-.5-.3-1.1-.7-1.4A4 4 0 0 1 8 2.5Z M6.6 13.5h2.8 M7 15h2",
  "arrow-right": "M2.5 8h10.5 M9.5 4.5 13.5 8l-4 3.5",
  plus: "M8 3v10 M3 8h10",
  reset: "M12.8 8A4.8 4.8 0 1 1 11 4.4 M12.8 3v3.4h-3.4",
};

export interface LabIconProps {
  name: LabIconName;
  className?: string;
}

export function LabIcon({ name, className }: LabIconProps) {
  const classes = ["lab-icon", className].filter(Boolean).join(" ");
  return (
    <svg
      className={classes}
      width="18"
      height="18"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

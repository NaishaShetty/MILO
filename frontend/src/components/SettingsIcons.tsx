// SettingsIcons.tsx
//
// Purpose
// -------
// Small inline-SVG icon set for the Settings page's category sidebar --
// one icon per real settings category `SettingsPage.tsx` already
// renders (General, MILO Personality, Speech & Voice, LLM Provider,
// Vision, Memory, Planning & Execution, Notifications, Data & Privacy,
// Integrations, About). Purely decorative, matching the design system's
// "no emoji as interface icons" rule used on Home/About.
export type SettingsIconName =
  | "general"
  | "personality"
  | "speech"
  | "llm"
  | "vision"
  | "memory"
  | "planning"
  | "notifications"
  | "privacy"
  | "integrations"
  | "about";

const PATHS: Record<SettingsIconName, string> = {
  general:
    "M8 5.2A2.8 2.8 0 1 0 8 10.8 2.8 2.8 0 0 0 8 5.2Z M8 1.5v1.4 M8 13.1v1.4 M14.5 8h-1.4 M2.9 8H1.5 M12.4 3.6l-1 1 M4.6 11.4l-1 1 M12.4 12.4l-1-1 M4.6 4.6l-1-1",
  personality: "M8 1.5s5.5 3 5.5 7-2.5 6-5.5 6-5.5-2.5-5.5-6 5.5-7 5.5-7Z M5.8 8.2s.6.9 2.2.9 2.2-.9 2.2-.9",
  speech: "M2.5 4h11v6h-7l-2.5 2.5V10H2.5V4Z M5 6.5h6 M5 8.3h3.5",
  llm: "M3 3h10v10H3V3Z M6 3V1.5 M10 3V1.5 M6 14.5V13 M10 14.5V13 M3 6H1.5 M3 10H1.5 M14.5 6H13 M14.5 10H13 M6 6h4v4H6V6Z",
  vision: "M1 8s2.8-4.5 7-4.5S15 8 15 8s-2.8 4.5-7 4.5S1 8 1 8Z M8 10a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z",
  memory:
    "M2.5 4.2c0-1 2.5-1.7 5.5-1.7s5.5.7 5.5 1.7-2.5 1.8-5.5 1.8-5.5-.8-5.5-1.8Z M2.5 4.2V11.8c0 1 2.5 1.7 5.5 1.7s5.5-.7 5.5-1.7V4.2 M2.5 8c0 1 2.5 1.8 5.5 1.8s5.5-.8 5.5-1.8",
  planning: "M3 12.5 8 3.5l5 9 M8 3.5v9 M5 12.5h6",
  notifications: "M8 2c-2.2 0-3.5 1.7-3.5 4v2.3L3 11h10l-1.5-2.7V6c0-2.3-1.3-4-3.5-4Z M6.4 13a1.7 1.7 0 0 0 3.2 0",
  privacy: "M4.5 7V5a3.5 3.5 0 0 1 7 0v2 M3.5 7h9v7h-9V7Z M8 10v1.5",
  integrations: "M6.2 9.8 3.8 12.2a2 2 0 1 1-2.8-2.8l2.4-2.4 M9.8 6.2l2.4-2.4a2 2 0 1 1 2.8 2.8L12.6 9 M5.5 10.5l5-5",
  about: "M8 1.5A6.5 6.5 0 1 0 8 14.5 6.5 6.5 0 0 0 8 1.5Z M8 7.3v3.7 M8 5v.1",
};

export interface SettingsIconProps {
  name: SettingsIconName;
  className?: string;
}

export function SettingsIcon({ name, className }: SettingsIconProps) {
  const classes = ["settings-icon", className].filter(Boolean).join(" ");
  return (
    <svg
      className={classes}
      width="18"
      height="18"
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

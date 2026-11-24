// Stroke icons (no emoji). Decorative by default; give the button an aria-label.
import type { ReactNode } from "react";

function Svg({ children }: { children: ReactNode }) {
  return (
    <svg className="icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {children}
    </svg>
  );
}

export const PlayIcon = () => (<Svg><path d="M7 5l12 7-12 7z" /></Svg>);
export const FlagIcon = () => (<Svg><path d="M6 21V4M6 5h12l-3 4 3 4H6" /></Svg>);
export const BookIcon = () => (<Svg><path d="M5 4h11a3 3 0 013 3v13H8a3 3 0 01-3-3zM5 17a3 3 0 013-3h11" /></Svg>);
export const FlaskIcon = () => (<Svg><path d="M9 3h6M10 3v6l-5 9a2 2 0 002 3h10a2 2 0 002-3l-5-9V3" /></Svg>);
export const MicIcon = () => (<Svg><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0014 0M12 18v3" /></Svg>);
export const GearIcon = () => (<Svg><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2" /></Svg>);
export const ArrowIcon = () => (<Svg><path d="M5 12h14M13 6l6 6-6 6" /></Svg>);
export const CheckIcon = () => (<Svg><path d="M5 12l5 5 9-10" /></Svg>);

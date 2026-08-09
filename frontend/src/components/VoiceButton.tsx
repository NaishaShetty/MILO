// VoiceButton.tsx
//
// Purpose
// -------
// The reusable mic/voice-trigger button (spec section 45's
// `VoiceButton`) -- purely presentational, driven by a real voice/
// speech state passed in by the caller (`SpeechContext`'s state today,
// `VoiceContext`'s state once Stage 4 wires ElevenLabs). Renders one
// of the spec's real voice states (section 19), never a fake "always
// idle" mic icon divorced from what's actually happening.
export type VoiceButtonState = "idle" | "listening" | "processing" | "error" | "unavailable";

const LABELS: Record<VoiceButtonState, string> = {
  idle: "Talk to MILO",
  listening: "Listening... tap to stop",
  processing: "Processing...",
  error: "Try again",
  unavailable: "Voice unavailable",
};

export interface VoiceButtonProps {
  state: VoiceButtonState;
  onClick?: () => void;
  className?: string;
}

export function VoiceButton({ state, onClick, className }: VoiceButtonProps) {
  const classes = ["voice-button", `voice-button--${state}`, className]
    .filter(Boolean)
    .join(" ");
  return (
    <button
      type="button"
      className={classes}
      onClick={onClick}
      disabled={state === "unavailable" || state === "processing"}
      aria-pressed={state === "listening"}
      aria-label={LABELS[state]}
      title={LABELS[state]}
    >
      <span className="voice-button__icon" aria-hidden="true">
        <MicIcon />
      </span>
      {state === "listening" && <span className="voice-button__ring" aria-hidden="true" />}
    </button>
  );
}

function MicIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" aria-hidden="true">
      <rect x="9" y="2" width="6" height="12" rx="3" fill="currentColor" />
      <path
        d="M5 11a7 7 0 0 0 14 0M12 18v3"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

// MiloDialogue.tsx
//
// Purpose
// -------
// The dialogue bubble MILO "speaks" through (spec section 20/22/34).
// Renders only real text a caller supplies -- e.g. the real composed
// response from `POST /api/v1/voice/speak`'s underlying text (Stage 4),
// or a real example instruction on Home/About. Never renders
// placeholder/lorem text; an empty/undefined `text` renders nothing.
export interface MiloDialogueProps {
  text?: string;
  /** Small caption above the bubble, e.g. "I'm listening!" */
  caption?: string;
  className?: string;
}

export function MiloDialogue({ text, caption, className }: MiloDialogueProps) {
  if (!text) {
    return null;
  }
  const classes = ["milo-dialogue", className].filter(Boolean).join(" ");
  return (
    <div className={classes}>
      {caption && <span className="milo-dialogue__caption">{caption}</span>}
      <div className="milo-dialogue__bubble">{text}</div>
    </div>
  );
}

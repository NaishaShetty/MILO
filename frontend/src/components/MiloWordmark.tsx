// MiloWordmark.tsx
//
// Purpose
// -------
// The "MILO •" brand mark (the supplied wordmark image, dot baked
// in) shown wherever MILO's name appears as a brand mark rather than
// body copy -- the nav bar (every page) and MILO Lab's hero title.
// Renders the real asset at /assets/milo/milo-wordmark.png (135x34,
// transparent) rather than a font recreation.
export interface MiloWordmarkProps {
  className?: string;
}

export function MiloWordmark({ className }: MiloWordmarkProps) {
  const classes = ["milo-wordmark", className].filter(Boolean).join(" ");
  return <img src="/assets/milo/milo-wordmark.png" alt="MILO" className={classes} draggable={false} />;
}

// MiloWordmark.tsx -- the "milo" brand mark: the robot's face-screen badge
// (two amber eyes on black) beside the name in Fredoka. Pure CSS/HTML.
export interface MiloWordmarkProps {
  className?: string;
}

export function MiloWordmark({ className }: MiloWordmarkProps) {
  return (
    <span className={["wordmark", className].filter(Boolean).join(" ")}>
      <span className="wordmark__box" aria-hidden="true">
        <span className="wordmark__eye" />
        <span className="wordmark__eye" />
      </span>
      <span>milo</span>
    </span>
  );
}

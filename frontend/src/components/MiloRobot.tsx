// MiloRobot.tsx
//
// MILO as a layered SVG with two rigs: a FRONT view (standing, listening,
// thinking, speaking, success, error) and a SIDE view (walk, run). Every
// part -- head, eyes (blinking), both arms (elbows in the side view), both
// legs (knees in the side view) -- is its own group, animated independently
// by CSS keyed on `data-pose` (see milo.css). Colours come from tokens.css;
// the glow is amber. `paused` freezes every animation (used by visual
// snapshots), and prefers-reduced-motion disables running/bouncing in CSS.
import { rigForPose } from "./miloPose";

export type MiloPose =
  | "idle"
  | "listening"
  | "asking"
  | "waiting"
  | "recovering"
  | "thinking"
  | "speaking"
  | "walk"
  | "run"
  | "success"
  | "error";

export type MiloRig = "front" | "side";

export interface MiloRobotProps {
  pose?: MiloPose;
  /** Direction of travel; the side rig mirrors to face it. */
  facing?: "left" | "right";
  /** Name of an object being carried (shown in the hands). */
  carrying?: string | null;
  paused?: boolean;
  /** Pixel width; height follows the 2:3 viewBox. */
  size?: number;
  className?: string;
}

const HOODIE = "#3b3535";
const HOODIE_DARK = "#2b2626";
const SKIN = "#1b1818"; // robotic hands / face screen
const SHOE = "#241f1f";
const SOLE = "#e9dfd0";
const AMBER = "#ffb347";

function Eyes({ happy, slanted }: { happy: boolean; slanted: boolean }) {
  if (happy) {
    return (
      <g className="milo-part milo-eyes" fill="none" stroke={AMBER} strokeWidth="5" strokeLinecap="round">
        <path d="M80 98 q8 -10 16 0" />
        <path d="M104 98 q8 -10 16 0" />
      </g>
    );
  }
  return (
    <g className="milo-part milo-eyes" fill={AMBER} filter="url(#milo-glow)">
      <rect x="80" y="86" width="14" height="22" rx="3" transform={slanted ? "rotate(14 87 97)" : undefined} />
      <rect x="106" y="86" width="14" height="22" rx="3" transform={slanted ? "rotate(-14 113 97)" : undefined} />
    </g>
  );
}

function Defs() {
  return (
    <defs>
      <filter id="milo-glow" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="2.5" result="b" />
        <feMerge>
          <feMergeNode in="b" />
          <feMergeNode in="SourceGraphic" />
        </feMerge>
      </filter>
    </defs>
  );
}

function FrontRig({ pose, carrying }: { pose: MiloPose; carrying: boolean }) {
  const happy = pose === "success";
  const slanted = pose === "error";
  return (
    <g className="milo-rig milo-rig--front">
      {/* legs + sneakers */}
      <g className="milo-part milo-leg milo-leg--l">
        <rect x="76" y="208" width="20" height="46" rx="8" fill={HOODIE_DARK} />
        <path d="M68 262 q0 -12 16 -12 h14 v14 h-30 z" fill={SHOE} />
        <rect x="66" y="262" width="34" height="6" rx="3" fill={SOLE} />
      </g>
      <g className="milo-part milo-leg milo-leg--r">
        <rect x="104" y="208" width="20" height="46" rx="8" fill={HOODIE_DARK} />
        <path d="M100 250 h14 q16 0 16 12 v2 h-30 z" fill={SHOE} />
        <rect x="100" y="262" width="34" height="6" rx="3" fill={SOLE} />
      </g>
      {/* left arm (viewer's left) */}
      <g className="milo-part milo-arm milo-arm--l">
        <rect x="42" y="136" width="22" height="64" rx="11" fill={HOODIE} />
        <circle cx="53" cy="206" r="11" fill={SKIN} />
      </g>
      {/* body */}
      <g className="milo-part milo-body">
        <path d="M56 130 q44 -16 88 0 l10 90 q-54 14 -108 0 z" fill={HOODIE} />
        <path d="M82 214 h36 l4 -26 h-44 z" fill={HOODIE_DARK} opacity="0.55" />
        <path d="M84 150 v26 M116 150 v26" stroke="#ffdcc2" strokeWidth="3.5" strokeLinecap="round" />
        <circle cx="84" cy="178" r="3" fill="#ffdcc2" />
        <circle cx="116" cy="178" r="3" fill="#ffdcc2" />
      </g>
      {/* right arm */}
      <g className="milo-part milo-arm milo-arm--r">
        <rect x="136" y="136" width="22" height="64" rx="11" fill={HOODIE} />
        <circle cx="147" cy="206" r="11" fill={SKIN} />
      </g>
      {carrying && (
        <g className="milo-part milo-carried">
          <rect x="82" y="190" width="36" height="26" rx="6" fill="#ff8a2b" stroke="#2a1810" strokeWidth="2.5" />
          <circle cx="86" cy="204" r="9" fill={SKIN} />
          <circle cx="114" cy="204" r="9" fill={SKIN} />
        </g>
      )}
      {/* head */}
      <g className="milo-part milo-head">
        <path d="M54 92 q0 -52 46 -52 q46 0 46 52 q0 34 -46 34 q-46 0 -46 -34 z" fill={HOODIE} />
        <rect x="68" y="66" width="64" height="58" rx="22" fill={SKIN} />
        <rect x="74" y="70" width="52" height="9" rx="4.5" fill="#ffffff" opacity="0.14" />
        <Eyes happy={happy} slanted={slanted} />
        {pose === "listening" && <path d="M148 96 q10 6 0 16" stroke={AMBER} strokeWidth="3" fill="none" strokeLinecap="round" />}
        {pose === "recovering" && (
          <path className="milo-sweat" d="M140 70 q6 8 0 12 q-6 -4 0 -12 z" fill="#ffd25a" stroke="#2a1810" strokeWidth="1.5" />
        )}
      </g>
      {pose === "asking" && (
        <g className="milo-part milo-ask" aria-label="asking">
          <circle cx="150" cy="30" r="16" fill="#fff6e5" stroke="#2a1810" strokeWidth="2.5" />
          <text x="150" y="37" textAnchor="middle" fontSize="20" fontWeight="700" fill="#b34a00">?</text>
        </g>
      )}
      {pose === "waiting" && (
        <g className="milo-part milo-wait" aria-label="waiting for you">
          <circle cx="152" cy="30" r="14" fill="#fff6e5" stroke="#2a1810" strokeWidth="2.5" />
          <path d="M152 22 v8 l6 4" stroke="#2a1810" strokeWidth="2.5" fill="none" strokeLinecap="round" />
        </g>
      )}
    </g>
  );
}

function SideRig({ pose, carrying }: { pose: MiloPose; carrying: boolean }) {
  return (
    <g className="milo-rig milo-rig--side">
      {/* far leg + arm (behind the body) */}
      <g className="milo-part milo-leg milo-leg--far">
        <g className="milo-thigh">
          <rect x="94" y="206" width="20" height="26" rx="9" fill={HOODIE_DARK} />
          <g className="milo-knee">
            <rect x="96" y="226" width="17" height="28" rx="8" fill={HOODIE_DARK} />
            <path d="M92 258 q0 -10 12 -10 h22 q6 0 6 8 v6 h-40 z" fill={SHOE} />
            <rect x="90" y="262" width="44" height="6" rx="3" fill={SOLE} />
          </g>
        </g>
      </g>
      <g className="milo-part milo-arm milo-arm--far">
        <g className="milo-upper">
          <rect x="92" y="136" width="18" height="36" rx="9" fill={HOODIE_DARK} />
          <g className="milo-elbow">
            <rect x="93" y="164" width="16" height="34" rx="8" fill={HOODIE_DARK} />
            <circle cx="101" cy="202" r="10" fill={SKIN} />
          </g>
        </g>
      </g>
      <g className="milo-part milo-body">
        <path d="M78 132 q24 -12 48 0 l8 88 q-40 10 -64 0 z" fill={HOODIE} />
        <path d="M120 150 v24" stroke="#ffdcc2" strokeWidth="3.5" strokeLinecap="round" />
        <path d="M92 196 h28 l2 -16 h-32 z" fill={HOODIE_DARK} opacity="0.55" />
      </g>
      {carrying && (
        <g className="milo-part milo-carried">
          <rect x="120" y="170" width="30" height="24" rx="6" fill="#ff8a2b" stroke="#2a1810" strokeWidth="2.5" />
        </g>
      )}
      <g className="milo-part milo-leg milo-leg--near">
        <g className="milo-thigh">
          <rect x="88" y="206" width="22" height="26" rx="9" fill={HOODIE} />
          <g className="milo-knee">
            <rect x="90" y="226" width="19" height="28" rx="8" fill={HOODIE} />
            <path d="M86 258 q0 -10 12 -10 h24 q6 0 6 8 v6 h-42 z" fill={SHOE} />
            <rect x="84" y="262" width="46" height="6" rx="3" fill={SOLE} />
          </g>
        </g>
      </g>
      <g className="milo-part milo-arm milo-arm--near">
        <g className="milo-upper">
          <rect x="90" y="136" width="20" height="38" rx="10" fill={HOODIE} />
          <g className="milo-elbow">
            <rect x="91" y="166" width="18" height="36" rx="9" fill={HOODIE} />
            <circle cx="100" cy="206" r="11" fill={SKIN} />
          </g>
        </g>
      </g>
      <g className="milo-part milo-head">
        <path d="M70 92 q0 -50 40 -50 q34 0 40 40 q2 38 -38 44 q-42 2 -42 -34 z" fill={HOODIE} />
        <rect x="104" y="66" width="46" height="54" rx="20" fill={SKIN} />
        <g className="milo-part milo-eyes" fill={AMBER} filter="url(#milo-glow)">
          <rect x="124" y="86" width="12" height="22" rx="3" />
        </g>
      </g>
      {pose === "run" && <path d="M60 150 h-18 M64 168 h-24" stroke="#2a1810" strokeWidth="3" strokeLinecap="round" opacity="0.35" />}
    </g>
  );
}

export function MiloRobot({
  pose = "idle",
  facing = "right",
  carrying = null,
  paused = false,
  size = 200,
  className,
}: MiloRobotProps) {
  const rig = rigForPose(pose);
  const classes = ["milo-robot", `milo-robot--${pose}`, paused ? "milo-robot--paused" : "", className]
    .filter(Boolean)
    .join(" ");
  // The side rig is drawn facing right; mirror it to face left.
  const flip = rig === "side" && facing === "left";
  return (
    <svg
      className={classes}
      data-pose={pose}
      data-rig={rig}
      data-carrying={carrying ? "true" : "false"}
      role="img"
      aria-label={`MILO the robot, ${pose}${carrying ? `, carrying the ${carrying}` : ""}`}
      viewBox="0 0 200 300"
      width={size}
      height={(size * 3) / 2}
    >
      <Defs />
      <ellipse className="milo-shadow" cx="100" cy="274" rx="52" ry="9" fill="#2a1810" opacity="0.18" />
      <g transform={flip ? "translate(200 0) scale(-1 1)" : undefined}>
        {rig === "front" ? (
          <FrontRig pose={pose} carrying={Boolean(carrying)} />
        ) : (
          <SideRig pose={pose} carrying={Boolean(carrying)} />
        )}
      </g>
    </svg>
  );
}


// MiloStatus.tsx
//
// Purpose
// -------
// The "MILO is Ready" / connection-state pill shown in the nav bar and
// hero sections across every page (spec section 12/43). Purely
// presentational -- like `MiloCharacter`, it takes a real, already-
// derived `state` prop rather than fetching anything itself; each page
// derives `state` from `AgentsContext`/`TaskContext`'s real polled
// data (wired in Stage 3), so this component can be reused identically
// everywhere without duplicating that derivation logic.
import { StatusPill } from "./StatusPill";

export type MiloConnectionState = "ready" | "busy" | "connecting" | "disconnected";

const CONFIG: Record<MiloConnectionState, { label: string; tone: "success" | "accent" | "warning" | "danger" }> = {
  ready: { label: "MILO is Ready", tone: "success" },
  busy: { label: "MILO is Working", tone: "accent" },
  connecting: { label: "Connecting...", tone: "warning" },
  disconnected: { label: "MILO is Disconnected", tone: "danger" },
};

export interface MiloStatusProps {
  state: MiloConnectionState;
}

export function MiloStatus({ state }: MiloStatusProps) {
  const { label, tone } = CONFIG[state];
  return (
    <StatusPill tone={tone} dot>
      {label}
    </StatusPill>
  );
}

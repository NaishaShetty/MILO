// NavBar.tsx
//
// Purpose
// -------
// Top navigation for the MILO application -- the seven routes exactly
// (spec: "The MILO frontend contains SEVEN pages, not eight... There
// is NO separate Mission Detail page"). Establishes MILO's identity
// (full name in the header, per spec's branding rule) and highlights
// the active route via `NavLink`'s built-in `isActive` styling hook,
// so this needs no manual `useLocation()` bookkeeping.
//
// Connection-state derivation (Phase 8.2)
// ----------------------------------------------------------------------
// `MiloStatus`'s pill is real, not decorative: `AgentsContext` already
// polls `GET /api/v1/agents` every 3s (see `AgentsContext.tsx`) -- that
// is this app's only existing "is the backend up" signal, so it is
// what drives "MILO is Ready" / "Connecting..." / "MILO is
// Disconnected" here. A `status === "error"` is NOT automatically
// "disconnected": `GET /agents` returns a 503 `agents_unavailable`
// whenever no simulator/orchestrator is wired up (a normal, common dev
// mode per that route's own docstring), which means the backend is
// reachable and healthy, just without a running orchestrator -- only a
// real network failure (no `ApiError`, `fetch` itself rejecting) is
// shown as "Disconnected". `"busy"` is derived from whether any
// registered agent is currently ACTIVE/THINKING (real per-agent state).
import { NavLink } from "react-router-dom";

import { ApiError } from "../api/client";
import { useAgents } from "../state/AgentsContext";
import { useMiloState } from "../state/MiloStateContext";
import { MiloAvatar } from "./MiloAvatar";
import { MiloStatus, type MiloConnectionState } from "./MiloStatus";
import { MiloWordmark } from "./MiloWordmark";

const NAV_LINKS: Array<{ to: string; label: string; end?: boolean }> = [
  { to: "/", label: "Home", end: true },
  { to: "/mission-control", label: "Mission Control" },
  { to: "/memory", label: "Memory" },
  { to: "/activity", label: "Activity" },
  { to: "/about", label: "About MILO" },
  { to: "/lab", label: "MILO Lab" },
  { to: "/settings", label: "Settings" },
];

const BUSY_STATES = new Set(["active", "thinking"]);

function deriveConnectionState(
  status: "idle" | "loading" | "success" | "error",
  agents: Array<{ state: string }>,
  error: unknown,
): MiloConnectionState {
  if (status === "error") {
    // A 503 agents_unavailable means "backend reachable, no
    // orchestrator running yet" -- not a disconnect. Anything else
    // (a real fetch failure) means the backend truly can't be reached.
    return error instanceof ApiError && error.category === "agents_unavailable"
      ? "ready"
      : "disconnected";
  }
  if (status === "loading" || status === "idle") {
    return "connecting";
  }
  return agents.some((agent) => BUSY_STATES.has(agent.state)) ? "busy" : "ready";
}

export function NavBar() {
  const { agents, status, error } = useAgents();
  const connectionState = deriveConnectionState(status, agents, error);
  const miloState = useMiloState();

  return (
    <header className="milo-navbar">
      <div className="milo-navbar__brand">
        <MiloWordmark className="milo-navbar__title" />
        <span className="milo-navbar__tagline">
          <span>Memory Integrated</span>
          <span>Language Oriented Robot</span>
        </span>
      </div>
      <nav className="milo-navbar__links" aria-label="Main navigation">
        {NAV_LINKS.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            end={link.end}
            className={({ isActive }) =>
              "milo-navbar__link" + (isActive ? " milo-navbar__link--active" : "")
            }
          >
            {link.label}
          </NavLink>
        ))}
      </nav>
      <div className="milo-navbar__meta">
        <MiloStatus state={connectionState} />
        <div className="milo-navbar__avatar">
          <MiloAvatar state={connectionState === "disconnected" ? "offline" : miloState} size="sm" />
        </div>
      </div>
    </header>
  );
}

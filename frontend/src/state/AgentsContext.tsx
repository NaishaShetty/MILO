// AgentsContext.tsx
//
// Purpose
// -------
// Global agent-status state (`GET /api/v1/agents`), shared by every
// page that shows "MILO At a Glance"/"MILO Status"/Lab's technical
// info, so each doesn't open its own redundant polling loop. A 503
// (`agents_unavailable` -- no orchestrator/registry wired up, e.g. the
// simulator is disabled) is surfaced as `status === "error"`, not
// treated as a crash -- pages must render a real "agents unavailable"
// state, never fabricate "Online".
import { createContext, useContext, useMemo } from "react";
import type { ReactNode } from "react";

import { listAgents } from "../api/agents";
import type { AgentSummary } from "../api/agentsTypes";
import type { PollingStatus } from "../hooks/usePolling";
import { usePolling } from "../hooks/usePolling";

const POLL_INTERVAL_MS = 3000;

export interface AgentsContextValue {
  agents: AgentSummary[];
  status: PollingStatus;
  error: unknown;
  refresh: () => void;
}

const AgentsContext = createContext<AgentsContextValue | null>(null);

export function AgentsProvider({ children }: { children: ReactNode }) {
  const { data, status, error, refresh } = usePolling(listAgents, {
    intervalMs: POLL_INTERVAL_MS,
    enabled: true,
  });

  const value = useMemo<AgentsContextValue>(
    () => ({ agents: data ?? [], status, error, refresh }),
    [data, status, error, refresh],
  );

  return <AgentsContext.Provider value={value}>{children}</AgentsContext.Provider>;
}

export function useAgents(): AgentsContextValue {
  const context = useContext(AgentsContext);
  if (!context) {
    throw new Error("useAgents() must be used within an <AgentsProvider>.");
  }
  return context;
}

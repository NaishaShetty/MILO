// agents.ts
//
// Purpose
// -------
// The *only* place in this frontend that issues an HTTP request to the
// backend's Phase 7 Agents API (`backend/api/routes/agents.py`).
// Mirrors `tasks.ts`/`execution.ts`'s "one file per domain" convention.
// Both routes 503 with `{"category": "agents_unavailable", ...}` when
// no orchestrator/registry has been wired up yet (e.g. simulator
// disabled) -- callers should treat that `ApiError` as "agent status
// unavailable," not a bug.

import { ApiError, request } from "./client";
import type { AgentSummary } from "./agentsTypes";

export { ApiError as AgentsApiError };

/** `GET /api/v1/agents` -- every registered agent's name and current state. */
export async function listAgents(): Promise<AgentSummary[]> {
  return request<AgentSummary[]>("/api/v1/agents");
}

/** `GET /api/v1/agents/{name}/status` -- one agent's current state. Throws `ApiError` (404) if unregistered. */
export async function getAgentStatus(name: string): Promise<AgentSummary> {
  return request<AgentSummary>(`/api/v1/agents/${encodeURIComponent(name)}/status`);
}

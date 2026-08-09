// agentsTypes.ts
//
// Purpose
// -------
// TypeScript types for the Phase 7 Agents API (`GET /api/v1/agents`,
// `GET /api/v1/agents/{name}/status`) served by
// `backend/api/routes/agents.py`. Mirrors `tasksTypes.ts`'s `AgentStateValue`
// (`backend/agents/contracts.py::AgentState`) -- re-exported here so
// `agents.ts` doesn't need to import from the tasks domain.

export type AgentStateValue = "idle" | "active" | "thinking" | "waiting" | "error" | "shutdown";

// Mirrors `AgentRegistry.snapshot_states()`'s per-entry shape, returned
// by both `GET /agents` (as a list) and `GET /agents/{name}/status`
// (as a single object).
export interface AgentSummary {
  name: string;
  state: AgentStateValue;
}

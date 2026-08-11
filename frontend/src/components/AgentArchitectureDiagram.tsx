// AgentArchitectureDiagram.tsx
//
// Purpose
// -------
// Visualizes MILO's real agent architecture (Phase 8.6 spec section 9):
// a static graph of the actual backend agents (`backend/agents/*.py`
// wrappers, orchestrated by `orchestration/orchestrator.py`), each
// node's live `AgentStateValue` sourced from `AgentsContext` (`GET
// /api/v1/agents`) -- the same real data `AgentStatusList` already
// renders as a flat list, laid out here as a graph instead. No new
// data source, no fictional agent: the node set is exactly
// `AgentStatusList.tsx`'s `AGENT_LABELS` keys, which mirror the
// backend's registered agent names.
import { useAgents } from "../state/AgentsContext";
import type { AgentStateValue } from "../api/agentsTypes";

const STATE_LABELS: Record<AgentStateValue, string> = {
  idle: "Idle",
  active: "Active",
  thinking: "Thinking",
  waiting: "Waiting",
  error: "Error",
  shutdown: "Shutdown",
};

interface AgentNode {
  name: string;
  label: string;
  /** Grid column/row within `.agent-architecture__grid` (1-indexed). */
  column: number;
  row: number;
}

// Mirrors the real orchestrator lifecycle
// (`backend/orchestration/orchestrator.py`): Vision/Memory/Navigation
// feed the Planner, which drives Execution, which is checked by
// Reflection. Speech sits alongside as an independent input agent, not
// part of the plan/execute chain.
const NODES: AgentNode[] = [
  { name: "vision", label: "Vision", column: 1, row: 1 },
  { name: "memory", label: "Memory", column: 2, row: 1 },
  { name: "navigation", label: "Navigation", column: 3, row: 1 },
  { name: "planner", label: "Planner", column: 2, row: 2 },
  { name: "execution", label: "Execution", column: 2, row: 3 },
  { name: "reflection", label: "Reflection", column: 2, row: 4 },
  { name: "speech", label: "Speech", column: 4, row: 1 },
];

export function AgentArchitectureDiagram() {
  const { agents, status, error } = useAgents();

  if (status === "error") {
    return (
      <p className="agent-architecture__unavailable">
        Agent architecture unavailable
        {error instanceof Error && error.message ? `: ${error.message}` : "."}
      </p>
    );
  }

  const byName = new Map(agents.map((agent) => [agent.name, agent.state]));

  return (
    <div className="agent-architecture">
      <div className="agent-architecture__grid">
        {NODES.map((node) => {
          const state = byName.get(node.name);
          return (
            <div
              key={node.name}
              className={
                "agent-architecture__node" +
                (state ? ` agent-architecture__node--${state}` : " agent-architecture__node--unknown")
              }
              style={{ gridColumn: node.column, gridRow: node.row }}
              title={state ? STATE_LABELS[state] : "Not yet registered"}
            >
              <span className="agent-architecture__node-label">{node.label}</span>
              <span className="agent-architecture__node-state">
                {state ? STATE_LABELS[state] : "Not registered"}
              </span>
            </div>
          );
        })}
      </div>
      <p className="agent-architecture__caption">
        Vision, Memory, and Navigation feed the Planner; Execution runs the plan and Reflection
        evaluates the outcome. Speech is an independent input agent.
      </p>
    </div>
  );
}

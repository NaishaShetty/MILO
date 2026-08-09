// AgentStatusList.tsx
//
// Purpose
// -------
// Renders real agent status from `AgentsContext` (`GET /api/v1/agents`)
// -- used by Home's "MILO At a Glance", Mission Control's "MILO
// Status", and MILO Lab's technical info, each with a different subset
// of agents. Never fabricates "Online": an agent not yet registered
// (before the first task has run, or when the simulator/registry is
// unavailable) is shown as "Not yet registered," and a fetch failure
// is shown as "Unavailable," using the real `AgentsContext` error
// state -- see that context's own docstring.
//
// Registered agent names are exactly `backend/agents/*.py`'s `name`
// class attributes: "vision", "memory", "planner", "navigation",
// "execution", "reflection", "speech" (see Session 3 audit notes) --
// this file does not invent a name the backend doesn't register.
import { useAgents } from "../state/AgentsContext";

const AGENT_LABELS: Record<string, string> = {
  vision: "Vision",
  memory: "Memory",
  planner: "Planning",
  navigation: "Navigation",
  execution: "Execution",
  reflection: "Reflection",
  speech: "Speech",
};

const STATE_LABELS: Record<string, string> = {
  idle: "Idle",
  active: "Active",
  thinking: "Thinking",
  waiting: "Waiting",
  error: "Error",
  shutdown: "Shutdown",
};

export interface AgentStatusListProps {
  /** Agent names (registry keys) to show, in this order. */
  names: string[];
}

export function AgentStatusList({ names }: AgentStatusListProps) {
  const { agents, status, error } = useAgents();

  if (status === "error") {
    return (
      <p className="agent-status-list__unavailable">
        Agent status unavailable
        {error instanceof Error && error.message ? `: ${error.message}` : "."}
      </p>
    );
  }

  const byName = new Map(agents.map((agent) => [agent.name, agent.state]));

  return (
    <ul className="agent-status-list">
      {names.map((name) => {
        const state = byName.get(name);
        return (
          <li key={name} className="agent-status-list__item">
            <span className="agent-status-list__name">{AGENT_LABELS[name] ?? name}</span>
            <span
              className={
                "agent-status-list__badge" +
                (state ? ` agent-status-list__badge--${state}` : " agent-status-list__badge--unknown")
              }
            >
              {state ? (STATE_LABELS[state] ?? state) : "Not yet registered"}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

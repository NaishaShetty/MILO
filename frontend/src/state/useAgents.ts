// useAgents.ts -- the AgentsContext context object and its hook, kept out of AgentsContext.tsx so that
// file only exports components (React Fast Refresh needs that).
import { createContext, useContext } from "react";

import type { AgentsContextValue } from "./AgentsContext";

export const AgentsContext = createContext<AgentsContextValue | null>(null);

export function useAgents(): AgentsContextValue {
  const context = useContext(AgentsContext);
  if (!context) {
    throw new Error("useAgents() must be used within an <AgentsProvider>.");
  }
  return context;
}

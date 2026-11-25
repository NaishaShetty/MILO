// useMiloState.ts -- the MiloStateContext context object and its hook, kept out of MiloStateContext.tsx so that
// file only exports components (React Fast Refresh needs that).
import { createContext, useContext } from "react";

import type { MiloState } from "./miloState";
import type { MiloStateContextValue } from "./MiloStateContext";

export const MiloStateContext = createContext<MiloStateContextValue | null>(null);

export function useMiloState(): MiloState {
  const context = useContext(MiloStateContext);
  if (!context) {
    throw new Error("useMiloState() must be used within a <MiloStateProvider>.");
  }
  return context.state;
}

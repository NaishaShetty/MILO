// useSettings.ts -- the SettingsContext context object and its hook, kept out of SettingsContext.tsx so that
// file only exports components (React Fast Refresh needs that).
import { createContext, useContext } from "react";

import type { SettingsContextValue } from "./SettingsContext";

export const SettingsContext = createContext<SettingsContextValue | null>(null);

export function useSettings(): SettingsContextValue {
  const context = useContext(SettingsContext);
  if (!context) {
    throw new Error("useSettings() must be used within a <SettingsProvider>.");
  }
  return context;
}

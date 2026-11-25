// useVoice.ts -- the VoiceContext context object and its hook, kept out of VoiceContext.tsx so that
// file only exports components (React Fast Refresh needs that).
import { createContext, useContext } from "react";

import type { VoiceContextValue } from "./VoiceContext";

export const VoiceContext = createContext<VoiceContextValue | null>(null);

export function useVoice(): VoiceContextValue {
  const context = useContext(VoiceContext);
  if (!context) {
    throw new Error("useVoice() must be used within a <VoiceProvider>.");
  }
  return context;
}

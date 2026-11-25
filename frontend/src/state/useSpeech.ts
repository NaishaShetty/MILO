// useSpeech.ts -- the SpeechContext context object and its hook, kept out of SpeechContext.tsx so that
// file only exports components (React Fast Refresh needs that).
import { createContext, useContext } from "react";

import type { SpeechContextValue } from "./SpeechContext";

export const SpeechContext = createContext<SpeechContextValue | null>(null);

export function useSpeech(): SpeechContextValue {
  const context = useContext(SpeechContext);
  if (!context) {
    throw new Error("useSpeech() must be used within a <SpeechProvider>.");
  }
  return context;
}

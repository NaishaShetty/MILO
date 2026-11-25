// useBrowserVoice.ts -- the BrowserVoice context object and its hook, kept out of BrowserVoice.tsx so that
// file only exports components (React Fast Refresh needs that).
import { createContext, useContext } from "react";

import type { BrowserVoiceValue } from "./BrowserVoice";

export const Ctx = createContext<BrowserVoiceValue | null>(null);

const OFF: BrowserVoiceValue = {
  enabled: false,
  setEnabled: () => undefined,
  canListen: false,
  canSpeak: false,
  unsupported: "Voice isn't available here.",
  listening: false,
  speaking: false,
  listen: () => Promise.resolve(""),
  stopListening: () => undefined,
  say: () => Promise.resolve(),
};

export function useBrowserVoice(): BrowserVoiceValue {
  return useContext(Ctx) ?? OFF;
}

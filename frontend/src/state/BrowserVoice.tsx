// BrowserVoice.tsx -- voice with the browser's own speech recognition and speech
// synthesis (no server, no key). An on/off switch (remembered), a visible "listening"
// state, and a plain fallback message when the browser can't do it.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Ctx } from "./useBrowserVoice";
import type { ReactNode } from "react";

type Recognition = {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

const STORAGE_KEY = "milo.browserVoice";

function recognitionClass(): (new () => Recognition) | null {
  const w = window as unknown as { SpeechRecognition?: new () => Recognition; webkitSpeechRecognition?: new () => Recognition };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export interface BrowserVoiceValue {
  /** The user's switch (remembered between visits). */
  enabled: boolean;
  setEnabled: (on: boolean) => void;
  canListen: boolean;
  canSpeak: boolean;
  /** Why voice can't be used here, in plain words (null if it can). */
  unsupported: string | null;
  listening: boolean;
  speaking: boolean;
  /** Listens once; resolves with what was heard ("" if nothing). */
  listen: () => Promise<string>;
  stopListening: () => void;
  /** Says `text` out loud (only when voice is on and supported). */
  say: (text: string) => Promise<void>;
}

export function BrowserVoiceProvider({ children }: { children: ReactNode }) {
  const Recog = typeof window !== "undefined" ? recognitionClass() : null;
  const canListen = Recog !== null;
  const canSpeak = typeof window !== "undefined" && "speechSynthesis" in window;
  const [enabled, setEnabledState] = useState(() => window.localStorage.getItem(STORAGE_KEY) === "1");
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const current = useRef<Recognition | null>(null);

  const setEnabled = useCallback((on: boolean) => {
    window.localStorage.setItem(STORAGE_KEY, on ? "1" : "0");
    setEnabledState(on);
    if (!on && "speechSynthesis" in window) window.speechSynthesis.cancel();
  }, []);

  const listen = useCallback(
    () =>
      new Promise<string>((resolve, reject) => {
        if (!Recog) {
          reject(new Error("unsupported"));
          return;
        }
        const r = new Recog();
        r.lang = "en-US";
        r.interimResults = false;
        r.maxAlternatives = 1;
        let heard = "";
        r.onresult = (e) => {
          heard = Array.from(e.results)
            .map((res) => res[0]?.transcript ?? "")
            .join(" ")
            .trim();
        };
        r.onerror = (e) => {
          setListening(false);
          reject(new Error(e.error));
        };
        r.onend = () => {
          setListening(false);
          current.current = null;
          resolve(heard);
        };
        current.current = r;
        setListening(true);
        r.start();
      }),
    [Recog],
  );

  const stopListening = useCallback(() => current.current?.stop(), []);

  const say = useCallback(
    (text: string) =>
      new Promise<void>((resolve) => {
        if (!enabled || !canSpeak || !text) {
          resolve();
          return;
        }
        const u = new SpeechSynthesisUtterance(text);
        u.onend = () => {
          setSpeaking(false);
          resolve();
        };
        u.onerror = () => {
          setSpeaking(false);
          resolve();
        };
        setSpeaking(true);
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(u);
      }),
    [enabled, canSpeak],
  );

  useEffect(() => () => current.current?.stop(), []);

  const unsupported =
    canListen && canSpeak
      ? null
      : !canListen && !canSpeak
        ? "This browser can't listen or speak. Type to MILO instead."
        : !canListen
          ? "This browser can't listen, but MILO can still talk. Type your answers."
          : "This browser can't speak, but MILO can still listen.";

  const value = useMemo<BrowserVoiceValue>(
    () => ({ enabled, setEnabled, canListen, canSpeak, unsupported, listening, speaking, listen, stopListening, say }),
    [enabled, setEnabled, canListen, canSpeak, unsupported, listening, speaking, listen, stopListening, say],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

/** Voice switched off and unavailable: what components get outside the provider. */

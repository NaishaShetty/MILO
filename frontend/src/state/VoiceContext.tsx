// VoiceContext.tsx
//
// Purpose
// -------
// Phase 8.2's ElevenLabs voice-output pipeline (spec section 16/18/20/21):
// when the active task (`TaskContext`) reaches a real terminal state
// (succeeded/failed/cancelled) it has not yet been spoken for, this
// calls the real `POST /api/v1/voice/speak` endpoint with that
// `task_id` -- the backend composes a grounded response from the
// task's own real fields (see `backend/voice/response_composer.py`)
// and returns real synthesized audio plus the exact text that
// produced it. This context plays that audio and exposes the text for
// `MiloDialogue` to render -- never fabricated text, never fake audio.
//
// Deliberately does NOT touch speech-to-text: `SpeechContext.tsx`'s
// existing Whisper-based mic capture/transcription is unchanged (see
// the Phase 8.2 plan's Stage 4 scoping) -- this context is the output
// half only.
//
// Graceful degradation
// ------------------------
// If voice is disabled/unavailable (the default in most environments
// -- no `ELEVENLABS_API_KEY`), `speak()` throws and this context
// simply never plays audio or shows a dialogue bubble; nothing else in
// the app depends on it. A task that fails to be "spoken" is still
// marked as spoken (never retried in a loop).
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";

import { speak as speakApi } from "../api/voice";
import { TERMINAL_TASK_STATUSES } from "../api/tasksTypes";
import { useTask } from "./TaskContext";

export type VoiceOutputState = "idle" | "speaking" | "error";

export interface VoiceContextValue {
  state: VoiceOutputState;
  /** The real text MILO most recently spoke (or is speaking), or `null` before anything has. */
  spokenText: string | null;
}

const VoiceContext = createContext<VoiceContextValue | null>(null);

export function VoiceProvider({ children }: { children: ReactNode }) {
  const { activeTask } = useTask();
  const [state, setState] = useState<VoiceOutputState>("idle");
  const [spokenText, setSpokenText] = useState<string | null>(null);
  const spokenTaskIds = useRef(new Set<string>());
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const objectUrlRef = useRef<string | null>(null);

  const releaseObjectUrl = useCallback(() => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  }, []);

  const activeTaskId = activeTask?.task_id ?? null;
  const activeTaskStatus = activeTask?.status ?? null;

  useEffect(() => {
    // Depends on the stable primitives (id/status), not the whole
    // `activeTask` object -- `TaskContext` hands back a *new* object
    // reference on every poll tick even when nothing meaningful
    // changed, and re-running this effect on every tick would set
    // this run's `cancelled` flag before its own in-flight
    // `speakApi()` call resolves, silently dropping the response.
    if (!activeTaskId || !activeTaskStatus) return;
    if (!TERMINAL_TASK_STATUSES.includes(activeTaskStatus)) return;
    if (spokenTaskIds.current.has(activeTaskId)) return;
    spokenTaskIds.current.add(activeTaskId);

    let cancelled = false;
    speakApi({ taskId: activeTaskId })
      .then(({ audioBlob, text }) => {
        if (cancelled) return;
        // The real text is set first, independent of anything below --
        // the dialogue bubble must show it even if audio playback
        // itself can't be set up for some reason.
        setSpokenText(text);
        setState("speaking");
        try {
          releaseObjectUrl();
          const url = URL.createObjectURL(audioBlob);
          objectUrlRef.current = url;
          if (audioRef.current) {
            audioRef.current.src = url;
            void audioRef.current.play().catch(() => {
              // Autoplay can be blocked by the browser -- not a voice
              // failure, just no audible playback; the dialogue bubble
              // still shows the real text.
              setState("idle");
            });
          }
        } catch {
          // Audio element/object-URL setup failed -- text is already
          // shown; just don't claim to be audibly speaking.
          setState("idle");
        }
      })
      .catch(() => {
        if (!cancelled) setState("error");
      });

    return () => {
      cancelled = true;
    };
  }, [activeTaskId, activeTaskStatus, releaseObjectUrl]);

  useEffect(() => releaseObjectUrl, [releaseObjectUrl]);

  return (
    <VoiceContext.Provider value={{ state, spokenText }}>
      {children}
      <audio
        ref={audioRef}
        onEnded={() => setState("idle")}
        onError={() => setState("error")}
        hidden
      />
    </VoiceContext.Provider>
  );
}

export function useVoice(): VoiceContextValue {
  const context = useContext(VoiceContext);
  if (!context) {
    throw new Error("useVoice() must be used within a <VoiceProvider>.");
  }
  return context;
}

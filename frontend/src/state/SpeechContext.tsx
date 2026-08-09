// SpeechContext.tsx
//
// Purpose
// -------
// Drives the browser side of the speech lifecycle (spec Part 8):
// `idle -> listening -> processing -> transcribing -> transcribed`,
// or `error` at any point, using `navigator.mediaDevices.getUserMedia`
// + `MediaRecorder` to capture audio and `speech.ts::transcribeAudio()`
// to reach Whisper. Deliberately stops at `transcribed`, not
// `task_created`: this context's only job is "microphone audio in,
// transcript text out" -- it never calls `createTask()` itself (that
// would make speech a second task-creation path alongside `tasks.ts`).
// The page using this context (Home/Mission Control, wired in the
// "Speech UI wiring" step) reads `transcript`, calls
// `useTask().submitInstruction(transcript, "speech")` itself, and then
// calls `markTaskCreated()`/`reset()` here -- one shared task-creation
// call site either way (see `tasks.ts`'s own docstring).
//
// Every failure mode (no `mediaDevices` API, permission denied, no
// speech captured, a transcription/backend error) is caught and
// mapped to a `SpeechErrorKind` -- never left to throw into the UI.
import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

import { mapSpeechError, transcribeAudio } from "../api/speech";
import type { SpeechErrorKind } from "../api/speechTypes";

export type SpeechState =
  | "idle"
  | "listening"
  | "processing"
  | "transcribing"
  | "transcribed"
  | "task_created"
  | "error";

export interface SpeechContextValue {
  state: SpeechState;
  transcript: string | null;
  errorKind: SpeechErrorKind | null;
  errorMessage: string | null;
  micSupported: boolean;
  startListening: () => Promise<void>;
  stopListening: () => void;
  markTaskCreated: () => void;
  reset: () => void;
}

const SpeechContext = createContext<SpeechContextValue | null>(null);

export function SpeechProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SpeechState>("idle");
  const [transcript, setTranscript] = useState<string | null>(null);
  const [errorKind, setErrorKind] = useState<SpeechErrorKind | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  const micSupported =
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices &&
    typeof navigator.mediaDevices.getUserMedia === "function" &&
    typeof window.MediaRecorder !== "undefined";

  function fail(kind: SpeechErrorKind, message: string) {
    setErrorKind(kind);
    setErrorMessage(message);
    setState("error");
  }

  function stopStream() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  const handleRecordingStopped = useCallback(async () => {
    stopStream();
    setState("processing");

    if (chunksRef.current.length === 0) {
      fail("no_speech_detected", "No audio was captured.");
      return;
    }

    const audioBlob = new Blob(chunksRef.current, {
      type: recorderRef.current?.mimeType || "audio/webm",
    });

    setState("transcribing");
    try {
      const result = await transcribeAudio(audioBlob);
      if (!result.text.trim()) {
        fail("no_speech_detected", "MILO didn't hear anything intelligible.");
        return;
      }
      setTranscript(result.text);
      setState("transcribed");
    } catch (error) {
      fail(mapSpeechError(error), error instanceof Error ? error.message : "Transcription failed.");
    }
  }, []);

  const startListening = useCallback(async () => {
    setErrorKind(null);
    setErrorMessage(null);
    setTranscript(null);

    if (!micSupported) {
      fail("mic_unavailable", "This browser does not support microphone capture.");
      return;
    }

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (error) {
      const name = error instanceof DOMException ? error.name : "";
      if (name === "NotAllowedError" || name === "SecurityError") {
        fail("permission_denied", "Microphone permission was denied.");
      } else {
        fail("mic_unavailable", "No microphone is available.");
      }
      return;
    }

    streamRef.current = stream;
    chunksRef.current = [];

    let recorder: MediaRecorder;
    try {
      recorder = new MediaRecorder(stream);
    } catch {
      stopStream();
      fail("mic_unavailable", "This browser cannot record audio.");
      return;
    }

    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data);
    };
    recorder.onstop = () => {
      void handleRecordingStopped();
    };
    recorderRef.current = recorder;
    recorder.start();
    setState("listening");
  }, [micSupported, handleRecordingStopped]);

  const stopListening = useCallback(() => {
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      recorderRef.current.stop();
    } else {
      stopStream();
    }
  }, []);

  const markTaskCreated = useCallback(() => setState("task_created"), []);

  const reset = useCallback(() => {
    stopStream();
    recorderRef.current = null;
    chunksRef.current = [];
    setState("idle");
    setTranscript(null);
    setErrorKind(null);
    setErrorMessage(null);
  }, []);

  const value = useMemo<SpeechContextValue>(
    () => ({
      state,
      transcript,
      errorKind,
      errorMessage,
      micSupported,
      startListening,
      stopListening,
      markTaskCreated,
      reset,
    }),
    [state, transcript, errorKind, errorMessage, micSupported, startListening, stopListening, markTaskCreated, reset],
  );

  return <SpeechContext.Provider value={value}>{children}</SpeechContext.Provider>;
}

export function useSpeech(): SpeechContextValue {
  const context = useContext(SpeechContext);
  if (!context) {
    throw new Error("useSpeech() must be used within a <SpeechProvider>.");
  }
  return context;
}

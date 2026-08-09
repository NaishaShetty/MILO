// TalkToMilo.tsx
//
// Purpose
// -------
// The "Talk to MILO" input -- text field, send button, microphone
// button, speech status/transcript -- shared by Home and Mission
// Control (spec: both pages have this section). A single component so
// there is exactly one text-submission and one speech-submission code
// path, both funneling into `TaskContext.submitInstruction` (see
// `tasks.ts`'s "one task-creation call site" rule). Submitting
// successfully (text or speech) navigates to Mission Control, the live
// dashboard for whatever task was just created.
import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { useSpeechToTask } from "../hooks/useSpeechToTask";
import { useTask } from "../state/TaskContext";

const SPEECH_STATUS_LABEL: Record<string, string> = {
  idle: "",
  listening: "Listening...",
  processing: "Processing audio...",
  transcribing: "Transcribing with Whisper...",
  transcribed: "Transcribed.",
  task_created: "Task created.",
  error: "",
};

const SPEECH_ERROR_LABEL: Record<string, string> = {
  mic_unavailable: "Microphone unavailable.",
  permission_denied: "Microphone permission was denied.",
  no_speech_detected: "No speech detected.",
  transcription_failed: "Transcription failed.",
  whisper_unavailable: "MILO's speech service (Whisper) is unavailable.",
  backend_unavailable: "Could not reach MILO's backend.",
};

export interface TalkToMiloProps {
  quickExamples?: string[];
  inputLabel?: string;
}

export function TalkToMilo({ quickExamples, inputLabel = "Instruction for MILO" }: TalkToMiloProps) {
  const navigate = useNavigate();
  const { submitInstruction, submitting, submitError } = useTask();
  const speech = useSpeechToTask();
  const [instruction, setInstruction] = useState("");

  const isListening = speech.state === "listening";
  const isBusySpeaking = speech.state === "processing" || speech.state === "transcribing";

  async function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed || submitting) return;
    try {
      await submitInstruction(trimmed, "text");
      setInstruction("");
      navigate("/mission-control");
    } catch {
      // `submitError` (from useTask()) already carries a safe message.
    }
  }

  function handleFormSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submit(instruction);
  }

  function handleMicClick() {
    if (isListening) {
      speech.stopListening();
    } else {
      speech.reset();
      void speech.startListening();
    }
  }

  return (
    <section className="talk-to-milo" aria-label="Talk to MILO">
      <p className="talk-to-milo__prompt">What would you like me to do?</p>

      <form className="talk-to-milo__form" onSubmit={handleFormSubmit}>
        <label htmlFor="talk-to-milo-input" className="talk-to-milo__label">
          {inputLabel}
        </label>
        <div className="talk-to-milo__row">
          <input
            id="talk-to-milo-input"
            type="text"
            className="talk-to-milo__input"
            placeholder="Type your instruction here..."
            value={instruction}
            onChange={(event) => setInstruction(event.target.value)}
            disabled={submitting}
          />
          <button
            type="button"
            className={"talk-to-milo__mic" + (isListening ? " talk-to-milo__mic--active" : "")}
            onClick={handleMicClick}
            disabled={isBusySpeaking}
            aria-pressed={isListening}
            aria-label={isListening ? "Stop listening" : "Speak an instruction"}
          >
            🎤
          </button>
          <button
            type="submit"
            className="talk-to-milo__send"
            disabled={submitting || instruction.trim().length === 0}
          >
            {submitting ? "Sending..." : "Send"}
          </button>
        </div>
      </form>

      {speech.state !== "idle" && (
        <p className="talk-to-milo__speech-status" aria-live="polite">
          {speech.state === "error"
            ? (speech.errorKind && SPEECH_ERROR_LABEL[speech.errorKind]) || speech.errorMessage
            : SPEECH_STATUS_LABEL[speech.state]}
        </p>
      )}

      {speech.transcript && (
        <p className="talk-to-milo__transcript">Heard: “{speech.transcript}”</p>
      )}

      {submitError && (
        <p className="talk-to-milo__error" role="alert">
          {submitError}
        </p>
      )}

      {quickExamples && quickExamples.length > 0 && (
        <div className="talk-to-milo__examples">
          <p className="talk-to-milo__examples-label">Try an example:</p>
          <div className="talk-to-milo__examples-list">
            {quickExamples.map((example) => (
              <button
                key={example}
                type="button"
                className="talk-to-milo__example"
                onClick={() => void submit(example)}
                disabled={submitting}
              >
                {example}
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

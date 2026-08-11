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
import type { FormEvent, KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";

import { HomeIcon } from "./HomeIcons";
import type { HomeIconName } from "./HomeIcons";
import { useSpeechToTask } from "../hooks/useSpeechToTask";
import { useTask } from "../state/TaskContext";
import { useVoice } from "../state/VoiceContext";

// Decorative only -- a keyword match on the example's own fixed
// wording (never derived from backend data), same idiom as
// HomePage.tsx's EXAMPLE_ICON map, generalized here since TalkToMilo
// is reused with different example copy per page.
function iconForExample(text: string): HomeIconName {
  const lower = text.toLowerCase();
  if (lower.includes("apple")) return "apple";
  if (lower.includes("mug") || lower.includes("cup")) return "mug";
  if (lower.includes("bottle")) return "bottle";
  return "question";
}

function SendIcon() {
  return (
    <svg viewBox="0 0 20 20" width="16" height="16" fill="none" aria-hidden="true">
      <path
        d="M17.5 2.5 2.5 8.75l5.5 2.25 2.25 5.5L17.5 2.5Z M8 11l4.5-4.5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg viewBox="0 0 20 20" width="16" height="16" fill="none" aria-hidden="true">
      <rect x="7.5" y="2" width="5" height="9" rx="2.5" fill="currentColor" />
      <path
        d="M4.5 9.5a5.5 5.5 0 0 0 11 0M10 15v2.5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
    </svg>
  );
}

function ChevronIcon() {
  return (
    <svg viewBox="0 0 16 16" width="12" height="12" fill="none" aria-hidden="true">
      <path d="M6 3.5 10.5 8 6 12.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

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
  /** The prompt line above the input -- Home's mockup ("What would you
   * like me to do?") and Mission Control's ("Give me an instruction in
   * natural language.") use different copy for the same shared panel. */
  prompt?: string;
  examplesLabel?: string;
  /** Mission Control's mockup shows each example as a full-width row
   * with a trailing chevron ("list"); Home's mockup shows them as
   * wrapped inline pills ("pills"). Same data, different mockup. */
  examplesVariant?: "list" | "pills";
  /** "console" (default) is Mission Control's multi-line command box
   * with the send button below it. "compact" is Home's mockup: a slim
   * single-line input with the mic/send as small square buttons inline
   * to its right. */
  layout?: "console" | "compact";
}

export function TalkToMilo({
  quickExamples,
  inputLabel = "Instruction for MILO",
  prompt = "Give me an instruction in natural language.",
  examplesLabel = "Try these examples",
  examplesVariant = "list",
  layout = "console",
}: TalkToMiloProps) {
  const navigate = useNavigate();
  const { submitInstruction, submitting, submitError } = useTask();
  const speech = useSpeechToTask();
  const voice = useVoice();
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
      // Barge-in: starting to talk to MILO while it's still speaking
      // interrupts that playback rather than fighting for the user's
      // attention alongside a fresh recording.
      if (voice.state === "speaking") voice.stop();
      speech.reset();
      void speech.startListening();
    }
  }

  function handleTextareaKeyDown(event: KeyboardEvent<HTMLTextAreaElement | HTMLInputElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit(instruction);
    }
  }

  const isCompact = layout === "compact";

  return (
    <section className={"talk-to-milo" + (isCompact ? " talk-to-milo--compact" : "")} aria-label="Talk to MILO">
      <p className="talk-to-milo__prompt">{prompt}</p>

      <form className="talk-to-milo__form" onSubmit={handleFormSubmit}>
        <label htmlFor="talk-to-milo-input" className="talk-to-milo__label">
          {inputLabel}
        </label>
        <div className="talk-to-milo__input-wrap">
          {isCompact ? (
            <input
              id="talk-to-milo-input"
              type="text"
              className="talk-to-milo__input"
              placeholder="Type your instruction here..."
              value={instruction}
              onChange={(event) => setInstruction(event.target.value)}
              onKeyDown={handleTextareaKeyDown}
              disabled={submitting}
            />
          ) : (
            <textarea
              id="talk-to-milo-input"
              className="talk-to-milo__input"
              placeholder="Type your instruction here..."
              value={instruction}
              onChange={(event) => setInstruction(event.target.value)}
              onKeyDown={handleTextareaKeyDown}
              disabled={submitting}
              rows={3}
            />
          )}
          {!isCompact && (
            <button
              type="button"
              className={"talk-to-milo__mic" + (isListening ? " talk-to-milo__mic--active" : "")}
              onClick={handleMicClick}
              disabled={isBusySpeaking}
              aria-pressed={isListening}
              aria-label={isListening ? "Stop listening" : "Speak an instruction"}
            >
              <MicIcon />
            </button>
          )}
        </div>
        {isCompact ? (
          <>
            <button
              type="button"
              className={"talk-to-milo__mic talk-to-milo__mic--compact" + (isListening ? " talk-to-milo__mic--active" : "")}
              onClick={handleMicClick}
              disabled={isBusySpeaking}
              aria-pressed={isListening}
              aria-label={isListening ? "Stop listening" : "Speak an instruction"}
            >
              <MicIcon />
            </button>
            <button
              type="submit"
              className="talk-to-milo__send talk-to-milo__send--compact"
              disabled={submitting || instruction.trim().length === 0}
              aria-label={submitting ? "Sending..." : "Send"}
            >
              <span className="talk-to-milo__send-icon" aria-hidden="true">
                <SendIcon />
              </span>
            </button>
          </>
        ) : (
          <button
            type="submit"
            className="talk-to-milo__send"
            disabled={submitting || instruction.trim().length === 0}
            aria-label={submitting ? "Sending..." : "Send"}
          >
            <span aria-hidden="true">{submitting ? "Sending..." : "Send to MILO"}</span>
            <span aria-hidden="true" className="talk-to-milo__send-icon">
              <SendIcon />
            </span>
          </button>
        )}
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
          <p className="talk-to-milo__examples-label">{examplesLabel}</p>
          <div className={`talk-to-milo__examples-list talk-to-milo__examples-list--${examplesVariant}`}>
            {quickExamples.map((example) => (
              <button
                key={example}
                type="button"
                className={`talk-to-milo__example talk-to-milo__example--${examplesVariant}`}
                onClick={() => void submit(example)}
                disabled={submitting}
              >
                <span className="talk-to-milo__example-icon" aria-hidden="true">
                  <HomeIcon name={iconForExample(example)} />
                </span>
                <span className="talk-to-milo__example-text">{example}</span>
                <span className="talk-to-milo__example-chevron" aria-hidden="true">
                  <ChevronIcon />
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

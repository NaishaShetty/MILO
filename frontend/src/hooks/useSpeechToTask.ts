// useSpeechToTask.ts
//
// Purpose
// -------
// The one place that connects `SpeechContext`'s transcript to
// `TaskContext`'s `submitInstruction` -- shared by Home and Mission
// Control (both have a mic button per spec) so there is exactly one
// "speech transcribed -> task created" glue path, not one per page.
// On success, navigates to Mission Control (the live dashboard) and
// marks the speech state machine `task_created`; on failure, leaves
// the transcript visible and lets `TaskContext.submitError` (already
// surfaced by whatever UI renders it) explain what went wrong --
// speech's own `error` state is reserved for speech-specific failures
// (mic/permission/transcription), not task-creation failures.
import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";

import { useSpeech } from "../state/SpeechContext";
import { useTask } from "../state/TaskContext";

export function useSpeechToTask() {
  const speech = useSpeech();
  const { submitInstruction } = useTask();
  const navigate = useNavigate();
  const handledTranscript = useRef<string | null>(null);

  useEffect(() => {
    if (speech.state !== "transcribed" || !speech.transcript) return;
    if (handledTranscript.current === speech.transcript) return;
    handledTranscript.current = speech.transcript;

    let cancelled = false;
    (async () => {
      try {
        await submitInstruction(speech.transcript as string, "speech");
        if (!cancelled) {
          speech.markTaskCreated();
          navigate("/mission-control");
        }
      } catch {
        // `TaskContext.submitError` already carries a safe message for
        // the page to render; speech stays in `transcribed` so the
        // user can see what was heard and retry.
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speech.state, speech.transcript]);

  return speech;
}

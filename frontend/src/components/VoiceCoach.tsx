// VoiceCoach.tsx -- when voice is on, MILO says its questions and approval requests out
// loud and listens for the answer ("yes" / "skip" / "cancel", or which choice).
import { useEffect, useRef } from "react";

import { decide } from "../api/tasks";
import type { PendingDecision, ReplyChoice } from "../api/tasksTypes";
import { useBrowserVoice } from "../state/BrowserVoice";
import { choiceFromSpeech, decisionFromSpeech, spokenQuestion } from "../utils/voiceAnswers";

export function VoiceCoach({
  taskId,
  pending,
  question,
  choices,
  onChoice,
}: {
  taskId?: string | null;
  pending?: PendingDecision | null;
  question?: string | null;
  choices?: ReplyChoice[];
  onChoice?: (c: ReplyChoice) => void;
}) {
  const voice = useBrowserVoice();
  const asked = useRef<string | null>(null);

  useEffect(() => {
    if (!voice.enabled) return;
    const key = pending ? `${taskId}:${pending.kind}:${pending.step_id ?? ""}:${pending.asked_at ?? ""}` : question ?? null;
    if (!key || asked.current === key) return;
    asked.current = key;
    void (async () => {
      if (pending && taskId) {
        await voice.say(spokenQuestion(pending));
        if (!voice.canListen) return;
        const heard = await voice.listen().catch(() => "");
        const choice = decisionFromSpeech(heard, pending.kind);
        if (choice) await decide(taskId, choice).catch(() => undefined);
      } else if (question) {
        await voice.say(question);
        if (!voice.canListen || !choices?.length || !onChoice) return;
        const heard = await voice.listen().catch(() => "");
        const picked = choiceFromSpeech(heard, choices);
        if (picked) onChoice(picked);
      }
    })();
  }, [voice, taskId, pending, question, choices, onChoice]);

  return null;
}

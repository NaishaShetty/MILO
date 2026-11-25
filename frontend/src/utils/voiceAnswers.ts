// voiceAnswers.ts -- turning a spoken answer into a decision or a choice.

const YES = /\b(yes|yeah|yep|sure|ok(ay)?|go ahead|do it|approve|fine|please do)\b/i;
const SKIP = /\b(no|nope|skip|don'?t|do not|leave it|not that)\b/i;
const CANCEL = /\b(cancel|stop|never ?mind|forget it)\b/i;

/** "yes, go ahead" -> approve; "skip that" -> skip; "cancel" -> cancel; else null. */
export function decisionFromSpeech(heard: string, kind: "step" | "plan"): "approve" | "skip" | "cancel" | null {
  if (CANCEL.test(heard)) return "cancel";
  if (SKIP.test(heard)) return kind === "plan" ? "cancel" : "skip";
  if (YES.test(heard)) return "approve";
  return null;
}

/** Picks the choice whose label shares the most words with what was heard ("the one on
 * the table" -> "the cup on the table"); null if nothing matches. */
export function choiceFromSpeech<T extends { label: string }>(heard: string, choices: T[]): T | null {
  const stop = new Set(["the", "a", "an", "on", "in", "one", "that", "this", "please", "it"]);
  const words = (s: string) => new Set(s.toLowerCase().split(/[^a-z0-9]+/).filter((w) => w && !stop.has(w)));
  const said = words(heard);
  let best: T | null = null;
  let bestScore = 0;
  for (const c of choices) {
    const score = [...words(c.label)].filter((w) => said.has(w)).length;
    if (score > bestScore) {
      best = c;
      bestScore = score;
    }
  }
  return best;
}

/** What MILO says out loud when it needs an answer. */
export function spokenQuestion(pending: { kind: "step" | "plan"; text?: string; why: string }): string {
  return pending.kind === "plan"
    ? "I worked out a plan. Shall I go ahead? Say yes, or cancel."
    : `${pending.text ?? "Can I do this?"} I'm asking because ${pending.why}. Say yes, or skip.`;
}

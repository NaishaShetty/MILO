// DecisionCard.tsx -- MILO is waiting for the user: approve or skip a risky step, or
// look over a plan it worked out itself (leave steps out, go ahead, or cancel).
import { useState } from "react";

import { ApiError } from "../api/client";
import { decide } from "../api/tasks";
import type { PendingDecision } from "../api/tasksTypes";

export function DecisionCard({ taskId, pending }: { taskId: string; pending: PendingDecision }) {
  const steps = pending.steps ?? [];
  const [keep, setKeep] = useState<Set<number>>(() => new Set(steps.map((s) => s.step_id)));
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const answer = async (choice: "approve" | "skip" | "cancel", edited?: boolean) => {
    setBusy(true);
    try {
      const chosen = edited ? steps.filter((s) => keep.has(s.step_id)).map((s) => ({ step_id: s.step_id })) : undefined;
      await decide(taskId, choice, chosen);
      setProblem(null);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "I couldn't hear that. Try again?");
    } finally {
      setBusy(false);
    }
  };

  if (pending.kind === "step") {
    return (
      <section className="card decision" role="alertdialog" aria-label="MILO needs your OK">
        <h2>Can I do this?</h2>
        <p>
          <strong>{pending.text}</strong> I'm asking because {pending.why}.
        </p>
        <div className="controls">
          <button type="button" className="btn btn--go" disabled={busy} onClick={() => void answer("approve")}>
            Yes, go ahead
          </button>
          <button type="button" className="btn" disabled={busy} onClick={() => void answer("skip")}>
            Skip that step
          </button>
        </div>
        {problem && <div className="notice notice--error" role="alert">{problem}</div>}
      </section>
    );
  }

  const edited = keep.size !== steps.length;
  return (
    <section className="card decision" role="alertdialog" aria-label="Check MILO's plan">
      <h2>Here's my plan</h2>
      <p className="muted">{pending.why} Untick anything you'd like me to leave out.</p>
      <ol className="steps">
        {steps.map((s) => (
          <li key={s.step_id}>
            <label>
              <input
                type="checkbox"
                checked={keep.has(s.step_id)}
                onChange={(e) => {
                  const next = new Set(keep);
                  if (e.target.checked) next.add(s.step_id);
                  else next.delete(s.step_id);
                  setKeep(next);
                }}
              />{" "}
              {s.text}
            </label>
          </li>
        ))}
      </ol>
      <div className="controls">
        <button
          type="button"
          className="btn btn--go"
          disabled={busy || keep.size === 0}
          onClick={() => void answer("approve", edited)}
        >
          {edited ? `Go ahead with ${keep.size} steps` : "Go ahead"}
        </button>
        <button type="button" className="btn" disabled={busy} onClick={() => void answer("cancel")}>
          Cancel
        </button>
      </div>
      {problem && <div className="notice notice--error" role="alert">{problem}</div>}
    </section>
  );
}

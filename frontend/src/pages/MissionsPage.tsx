// MissionsPage.tsx -- one mission: title and status, MILO walking along the
// steps, step cards, MILO's thoughts, what MILO sees, the reflection options,
// what he learned, and Stop / Try again / Replay controls.
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { perceive } from "../api/vision";
import { MiloActor } from "../components/MiloActor";
import { MissionTrack } from "../components/MissionTrack";
import { MiloRobot } from "../components/MiloRobot";
import { directMilo } from "../state/miloDirector";
import { useTask } from "../state/TaskContext";
import { confidenceWord, stepTitle } from "../utils/friendly";
import { ApiError } from "../api/client";
import { readableWording, saveTaskAsSkill } from "../api/skills";

const WHO: Record<string, string> = { memory: "M", planner: "P", eyes: "E", hands: "H", reflect: "R" };
const TERMINAL = ["succeeded", "failed", "cancelled"];

function statusLine(status: string, cancelRequested?: boolean): { pill: string; tone: string } {
  if (cancelRequested && !TERMINAL.includes(status)) return { pill: "Stopping...", tone: "pill--butter" };
  switch (status) {
    case "succeeded":
      return { pill: "Mission complete", tone: "" };
    case "failed":
      return { pill: "Didn't work out", tone: "pill--coral" };
    case "cancelled":
      return { pill: "Stopped", tone: "pill--butter" };
    case "created":
    case "parsing":
    case "retrieving_memory":
    case "planning":
      return { pill: "Getting ready", tone: "pill--butter" };
    default:
      return { pill: "Working on it", tone: "pill--butter" };
  }
}

function SeesPanel({ prompt, refreshKey }: { prompt: string; refreshKey: unknown }) {
  const [image, setImage] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const look = useCallback(() => {
    perceive(prompt || "object.", false)
      .then((r) => {
        setImage(r.camera_image_png_b64);
        setProblem(null);
      })
      .catch(() => setProblem("I can't get a picture right now. Is the simulator running?"));
  }, [prompt]);
  useEffect(() => {
    look();
    // refresh whenever the mission moves on a step
  }, [look, refreshKey]);
  return (
    <section className="card" aria-label="What MILO sees">
      <div className="mission-head">
        <h2>What MILO sees</h2>
        <button type="button" className="btn" onClick={look}>
          Look again
        </button>
      </div>
      <div className="camera">
        {image ? (
          <img alt="MILO's camera view of the room" src={`data:image/png;base64,${image}`} />
        ) : (
          <span className="muted">{problem ?? "Looking..."}</span>
        )}
      </div>
    </section>
  );
}

function SaveAsSkill({ taskId, wording }: { taskId: string; wording: string }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(wording);
  const [said, setSaid] = useState<{ text: string; bad: boolean } | null>(null);
  const save = async () => {
    try {
      const skill = await saveTaskAsSkill(taskId, name.trim() || wording);
      setSaid({ text: `Saved. Say "${readableWording(skill.wording)}" and I'll do it again with whatever you name.`, bad: false });
      setOpen(false);
    } catch (error) {
      setSaid({ text: error instanceof ApiError ? error.message : "I couldn't save that. Is MILO's server running?", bad: true });
    }
  };
  return (
    <div className="save-skill">
      {open ? (
        <span className="ask__row">
          <input className="input" aria-label="Skill name" value={name} onChange={(e) => setName(e.target.value)} />
          <button type="button" className="btn btn--go" onClick={() => void save()}>
            Save skill
          </button>
        </span>
      ) : (
        !said && (
          <button type="button" className="chip" onClick={() => setOpen(true)}>
            Save as skill
          </button>
        )
      )}
      {said && (
        <p className={`notice${said.bad ? " notice--error" : ""}`} role={said.bad ? "alert" : "status"}>
          {said.text}
        </p>
      )}
    </div>
  );
}

interface NovelInfo {
  source?: "skill" | "model" | "";
  note?: string | null;
}

export function MissionsPage() {
  const navigate = useNavigate();
  const { activeTask, activeTaskStatus, history, setActiveTaskId, cancelActive, cancelling, submitInstruction, lastReply } =
    useTask();

  if (!activeTask) {
    const latest = history[0];
    return (
      <div className="card empty">
        <MiloRobot pose="idle" size={140} />
        <h2>{activeTaskStatus === "loading" ? "Fetching the mission..." : "No mission yet"}</h2>
        <p>{lastReply?.text ?? "Give MILO a job on the Play page and you'll watch it happen here."}</p>
        <button type="button" className="btn btn--go" onClick={() => navigate("/")}>
          Go to Play
        </button>
        {latest && (
          <p>
            <button type="button" className="chip" onClick={() => setActiveTaskId(latest.task_id)}>
              Open the last mission: {latest.user_request}
            </button>
          </p>
        )}
      </div>
    );
  }

  const steps = activeTask.current_plan?.steps ?? [];
  const direction = directMilo(activeTask);
  const finished = TERMINAL.includes(activeTask.status);
  const line = statusLine(activeTask.status, activeTask.cancel_requested);
  // "novel" is chosen by MILO itself, never a planner the user can ask for
  const chosenPlanner = activeTask.planner && activeTask.planner !== "novel" ? activeTask.planner : undefined;
  const retry = () => void submitInstruction(activeTask.user_request, activeTask.input_source, chosenPlanner);
  const novel = activeTask.planner === "novel" ? (activeTask.current_plan?.metadata?.novel as NovelInfo | undefined) ?? {} : null;
  const seconds = activeTask.metrics.total_ms ? Math.round(activeTask.metrics.total_ms / 1000) : null;

  return (
    <div className="missions">
      <div className="missions__main">
        <section className="card">
          <div className="mission-head">
            <div>
              <span className={`pill ${line.tone}`}>{line.pill}</span>
              <h1>{activeTask.user_request || "A mission"}</h1>
              <span className="muted">
                {steps.length > 0 ? `${activeTask.completed_steps.length} of ${steps.length} steps done` : "Making a plan..."}
                {seconds !== null ? ` · took about ${seconds} seconds` : ""}
                {activeTask.planner ? ` · planner: ${activeTask.planner.replace("_", " ")}` : ""}
              </span>
            </div>
            <div className="controls">
              {!finished && (
                <button type="button" className="btn" disabled={cancelling || activeTask.cancel_requested} onClick={() => void cancelActive()}>
                  Stop
                </button>
              )}
              {finished && activeTask.status !== "succeeded" && (
                <button type="button" className="btn btn--sun" onClick={retry}>
                  Try again
                </button>
              )}
              {finished && (
                <button type="button" className="btn" onClick={retry}>
                  Replay
                </button>
              )}
            </div>
          </div>
          {novel && (
            <p className="notice" role="status">
              {novel.source === "skill"
                ? "I've done something like this before, so I'm using what I learned."
                : "I don't know this one yet, so I'm working it out."}
              {novel.note ? ` ${novel.note}` : ""}
            </p>
          )}
          {activeTask.status === "succeeded" && <SaveAsSkill taskId={activeTask.task_id} wording={activeTask.user_request} />}
          {activeTask.planner_note && <div className="notice">{activeTask.planner_note}</div>}
          {activeTask.cancel_summary && <div className="notice">{activeTask.cancel_summary}</div>}
          {activeTask.answer && <div className="notice">{activeTask.answer}</div>}
          <MissionTrack steps={steps} direction={direction} />
        </section>

        <section>
          <h2>The path</h2>
          {steps.length === 0 ? (
            <div className="card empty">MILO is still thinking about the steps. They'll show up here.</div>
          ) : (
            <div className="steps">
              {steps.map((step) => (
                <div
                  key={step.step_id}
                  className={
                    "step" +
                    (step.status === "completed" ? " step--done" : step.status === "running" ? " step--current" : step.status === "failed" ? " step--failed" : "")
                  }
                >
                  <span className="pill">{step.status === "completed" ? "Done" : step.status === "running" ? "Now" : step.status === "failed" ? "Oops" : "Next"}</span>
                  <div className="step__title">{stepTitle(step)}</div>
                  <div className="step__meta">{step.explanation ?? `${step.action} · ${step.target ?? ""}`}</div>
                  {typeof step.confidence === "number" && (
                    <div className="step__meta" title={`${Math.round(step.confidence * 100)}% chance this works`}>
                      <strong>{confidenceWord(step.confidence)}</strong>
                      {step.why ? ` · Why: ${step.why}` : ""}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        <section>
          <h2>MILO's thoughts</h2>
          {(activeTask.thoughts ?? []).length === 0 ? (
            <div className="card empty">MILO hasn't said anything yet.</div>
          ) : (
            <div className="thoughts" aria-live="polite">
              {activeTask.thoughts?.map((thought, index) => (
                <div key={`${thought.at}-${index}`} className="thought">
                  <span className="thought__who" aria-hidden="true">
                    {WHO[thought.kind] ?? "M"}
                  </span>
                  <span className="thought__text">{thought.text}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>

      <aside className="missions__side">
        <div style={{ position: "relative", height: 150 }}>
          <MiloActor direction={{ ...direction, x: 0.5 }} size={110} />
        </div>
        <SeesPanel prompt={activeTask.objects.join(". ")} refreshKey={activeTask.current_step ?? activeTask.status} />
        <section className="card" aria-label="If something goes wrong">
          <h2>If something goes wrong</h2>
          <div className="options">
            <div className="option option--mint"><strong>Carry on</strong><br />Everything worked, so MILO saves what it learned.</div>
            <div className="option option--coral"><strong>Try again</strong><br />A hiccup. Same plan, one more go.</div>
            <div className="option option--butter"><strong>New plan</strong><br />Route blocked? MILO makes a different plan.</div>
            <div className="option option--peach"><strong>Stop</strong><br />Not fixable. MILO explains why.</div>
          </div>
          <p className="muted">Replans so far: {activeTask.metrics.replans}</p>
        </section>
        <section className="card" aria-label="What MILO learned">
          <h2>What MILO learned</h2>
          {(activeTask.learned ?? []).length === 0 ? (
            <p className="muted">Nothing new yet. Finished missions teach MILO where things live.</p>
          ) : (
            <ul>{activeTask.learned?.map((line2) => <li key={line2}>{line2}</li>)}</ul>
          )}
        </section>
      </aside>
    </div>
  );
}

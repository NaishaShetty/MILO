// PlayPage.tsx -- the Home ("Play") space: greeting, one big input with a mic,
// example chips, planner picker, "what can MILO do?", recent missions, the
// little helpers, a first-run tour, and the playroom where MILO runs.
import { useEffect, useState } from "react";
import type { KeyboardEvent } from "react";
import { useNavigate } from "react-router-dom";

import { getTaskLibrary } from "../api/tasks";
import type { PlannerChoice, TaskKind, TaskState } from "../api/tasksTypes";
import { ArrowIcon, MicIcon } from "../components/Icons";
import { MiloActor } from "../components/MiloActor";
import { MiloRobot } from "../components/MiloRobot";
import { PlannerPicker } from "../components/PlannerPicker";
import { PLANNER_OPTIONS } from "../components/plannerOptions";
import { useAgents } from "../state/useAgents";
import { directMilo } from "../state/miloDirector";
import { useSpeech } from "../state/useSpeech";
import { useTask } from "../state/useTask";
import { useSpeechToTask } from "../hooks/useSpeechToTask";
import { relativeDay } from "../utils/friendly";
import { VoiceCoach } from "../components/VoiceCoach";
import { VoiceToggle } from "../components/VoiceToggle";
import { useBrowserVoice } from "../state/useBrowserVoice";

const EXAMPLES = ["Put the apple in the fridge", "Find the mug", "Pick up the book", "Open the drawer"];
const TOUR_KEY = "milo.tourSeen";

const HELPERS: Array<{ letter: string; name: string; agent: string; resting: string }> = [
  { letter: "E", name: "Eyes", agent: "vision", resting: "Watching the room" },
  { letter: "P", name: "Planner", agent: "planner", resting: "" },
  { letter: "M", name: "Memory", agent: "memory", resting: "Ready to recall" },
  { letter: "H", name: "Hands", agent: "execution", resting: "Waiting" },
  { letter: "R", name: "Reflect", agent: "reflection", resting: "Resting" },
  { letter: "V", name: "Voice", agent: "speech", resting: "Mic ready" },
];
const HELPER_COLORS = ["var(--apricot)", "var(--peach)", "var(--coral)", "var(--coral)", "var(--butter)", "var(--mint)"];

function statusWord(state: string | undefined, resting: string): string {
  switch (state) {
    case "active":
      return "Busy";
    case "thinking":
      return "Thinking";
    case "waiting":
      return "Waiting";
    case "error":
      return "Needs a hand";
    default:
      return resting;
  }
}

function missionLabel(task: TaskState): { pill: string; tone: string; detail: string } {
  const steps = task.current_plan?.steps.length ?? 0;
  if (task.status === "succeeded") {
    return {
      pill: "Done",
      tone: "",
      detail: [steps ? `${steps} steps` : null, task.retrieved_memories.length ? "memory helped" : null]
        .filter(Boolean)
        .join(" · "),
    };
  }
  if (task.status === "failed") return { pill: "Didn't work", tone: "pill--coral", detail: "Tap to see what happened" };
  if (task.status === "cancelled") return { pill: "Stopped", tone: "pill--butter", detail: "You stopped this one" };
  return { pill: "In progress", tone: "pill--butter", detail: "Tap to watch" };
}

export function PlayPage() {
  const navigate = useNavigate();
  const { activeTask, history, submitInstruction, submitting, submitError, lastReply, cancelActive, setActiveTaskId } =
    useTask();
  const { agents } = useAgents();
  const speech = useSpeechToTask();
  const { micSupported } = useSpeech();
  const [text, setText] = useState("");
  const [planner, setPlanner] = useState<PlannerChoice>("rule_based");
  const [library, setLibrary] = useState<TaskKind[] | null>(null);
  const [showLibrary, setShowLibrary] = useState(false);
  const [floorX, setFloorX] = useState<number | null>(null);
  const [tour, setTour] = useState(() => {
    try {
      return window.localStorage.getItem(TOUR_KEY) !== "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    if (!showLibrary || library) return;
    getTaskLibrary().then(setLibrary).catch(() => setLibrary([]));
  }, [showLibrary, library]);

  const browserVoice = useBrowserVoice();
  const useBrowserMic = browserVoice.enabled && browserVoice.canListen;
  const baseDirection = directMilo(activeTask, lastReply?.text, lastReply?.kind === "clarify");
  const direction = browserVoice.listening ? { ...baseDirection, pose: "listening" as const, speech: "I'm listening..." } : baseDirection;
  // Tapping the floor sends MILO there (only while no mission is moving him).
  const shown = floorX !== null && direction.x === null ? { ...direction, x: floorX, pose: "walk" as const } : direction;

  async function send(instruction: string) {
    const trimmed = instruction.trim();
    if (!trimmed || submitting) return;
    try {
      const result = await submitInstruction(trimmed, "text", planner);
      setText("");
      setFloorX(null);
      if (result.kind === "task") navigate("/missions");
    } catch {
      // `submitError` carries a sentence to show.
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") void send(text);
    if (event.key === "Escape") {
      setText("");
      if (activeTask && !["succeeded", "failed", "cancelled"].includes(activeTask.status)) void cancelActive();
    }
  }

  function dismissTour() {
    setTour(false);
    try {
      window.localStorage.setItem(TOUR_KEY, "1");
    } catch {
      // not persisted; fine
    }
  }

  const listening = speech.state === "listening";
  const recent = history.slice(0, 3);

  return (
    <div>
      <div className="play">
        <section className="stage" aria-label="MILO">
          <div className="bubble" role="status">
            {listening ? "I'm listening..." : shown.speech}
          </div>
          <div className="milo-home">
            <MiloRobot pose={listening ? "listening" : shown.x === null ? shown.pose : "idle"} size={200} />
          </div>
        </section>

        <section>
          <div className="greeting">Hello there</div>
          <h1 className="hero-title">
            What should we <em>do</em> today?
          </h1>

          <div className="card ask">
            <label htmlFor="ask-input" className="muted" style={{ fontWeight: 700 }}>
              Tell MILO in plain words
            </label>
            <div className="ask__row">
              <input
                id="ask-input"
                className="input"
                value={text}
                placeholder="Put the apple in the fridge..."
                onChange={(event) => setText(event.target.value)}
                onKeyDown={onKeyDown}
                disabled={submitting}
              />
              <button
                type="button"
                className="btn btn--icon btn--sun"
                aria-label={listening || browserVoice.listening ? "Stop listening" : "Talk to MILO"}
                disabled={(!micSupported && !useBrowserMic) || submitting}
                title={micSupported || useBrowserMic ? "Talk to MILO" : "Your browser can't use the microphone here"}
                onClick={() => {
                  if (useBrowserMic) {
                    if (browserVoice.listening) browserVoice.stopListening();
                    else
                      void browserVoice
                        .listen()
                        .then((heard) => {
                          if (heard) void send(heard);
                        })
                        .catch(() => undefined);
                    return;
                  }
                  if (listening) speech.stopListening();
                  else void speech.startListening();
                }}
              >
                <MicIcon />
              </button>
              <button type="button" className="btn btn--go" disabled={!text.trim() || submitting} onClick={() => void send(text)}>
                Go! <ArrowIcon />
              </button>
            </div>
            <VoiceToggle />
            <VoiceCoach
              question={lastReply?.kind === "clarify" ? lastReply.text : null}
              choices={lastReply?.choices}
              onChoice={(c) => void submitInstruction(c.instruction, "speech", undefined, c.object_id).catch(() => undefined)}
            />
            <div className="chips" aria-label="Try one">
              <span className="muted">Try one:</span>
              {EXAMPLES.map((example) => (
                <button key={example} type="button" className="chip" onClick={() => void send(example)}>
                  {example}
                </button>
              ))}
            </div>
            <div className="ask__row">
              <PlannerPicker value={planner} onChange={setPlanner} disabled={submitting} />
              <button type="button" className="chip" aria-expanded={showLibrary} onClick={() => setShowLibrary((v) => !v)}>
                What can MILO do?
              </button>
            </div>
            {showLibrary && (
              <div className="library" aria-label="What MILO can do">
                {library === null && <p className="muted">Looking that up...</p>}
                {library?.length === 0 && (
                  <p className="muted">I couldn't load the list. Make sure MILO's server is running, then try again.</p>
                )}
                {library?.map((kind) => (
                  <div key={kind.id} className="library__item">
                    <strong>{kind.title}</strong> <span className="muted">{kind.summary}</span>
                    <div className="chips">
                      {kind.examples.map((example) => (
                        <button key={example} type="button" className="chip" onClick={() => setText(example)}>
                          {example}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {submitError && (
              <div className="notice notice--error" role="alert">
                {submitError}
              </div>
            )}
            {speech.state === "error" && speech.errorMessage && (
              <div className="notice notice--error" role="alert">
                {speech.errorMessage} Try typing instead.
              </div>
            )}
            {lastReply && (
              <div className="notice" role="status">
                {lastReply.text}
                {lastReply.choices && lastReply.choices.length > 0 && (
                  <div className="filters" role="group" aria-label="Answers">
                    {lastReply.choices.map((c) => (
                      <button
                        key={`${c.label}-${c.object_id ?? ""}`}
                        type="button"
                        className="chip"
                        disabled={submitting}
                        onClick={() => void submitInstruction(c.instruction, "text", undefined, c.object_id).catch(() => undefined)}
                      >
                        {c.label}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          <div className="mission-head" style={{ marginTop: 24 }}>
            <h2>Recent missions</h2>
            <button type="button" className="btn" onClick={() => navigate("/missions")}>
              See all <ArrowIcon />
            </button>
          </div>
          {recent.length === 0 ? (
            <div className="card empty">No missions yet. Try one of the examples above and watch MILO go!</div>
          ) : (
            <div className="missions-row">
              {recent.map((task) => {
                const label = missionLabel(task);
                return (
                  <button
                    key={task.task_id}
                    type="button"
                    className="card mission-card"
                    onClick={() => {
                      setActiveTaskId(task.task_id);
                      navigate("/missions");
                    }}
                  >
                    <span className={`pill ${label.tone}`}>{label.pill}</span>
                    <h3>{task.user_request || task.goal || "A mission"}</h3>
                    <span className="muted">
                      {label.detail || "—"}
                      {task.created_at ? ` · ${relativeDay(task.created_at)}` : ""}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </section>
      </div>

      <h2 style={{ marginTop: 24 }}>The playroom</h2>
      <div
        className="playroom"
        role="button"
        tabIndex={0}
        aria-label="The playroom. Tap the floor to send MILO there."
        onClick={(event) => {
          const rect = event.currentTarget.getBoundingClientRect();
          if (direction.x === null) setFloorX(Math.min(0.95, Math.max(0.05, (event.clientX - rect.left) / rect.width)));
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") setFloorX(0.6);
        }}
      >
        <span className="playroom__hint muted">Tap the floor to send MILO anywhere</span>
        <div className="playroom__floor" />
        <MiloActor direction={shown} size={90} />
      </div>

      <h2 style={{ marginTop: 24 }}>MILO's little helpers</h2>
      <div className="helpers">
        {HELPERS.map((helper, index) => {
          const agent = agents.find((a) => a.name === helper.agent);
          const resting =
            helper.name === "Planner" ? PLANNER_OPTIONS.find((o) => o.value === planner)?.label ?? "" : helper.resting;
          const word = statusWord(agent?.state, resting);
          return (
            <div
              key={helper.name}
              className={"helper" + (agent?.state === "active" || agent?.state === "thinking" ? " helper--busy" : "")}
              style={{ background: HELPER_COLORS[index] }}
            >
              <span className="helper__letter" aria-hidden="true">
                {helper.letter}
              </span>
              <span>
                <strong>{helper.name}</strong>
                <br />
                <span className="muted">{word}</span>
              </span>
            </div>
          );
        })}
      </div>

      {tour && (
        <div className="card tour" role="dialog" aria-label="Quick tour">
          <h3>Welcome to MILO!</h3>
          <p>
            Type a job (or tap the mic), press Go, and MILO will run around the playroom to do it. Watch his
            thoughts on the Missions page, and see what he remembers on the Memory page.
          </p>
          <button type="button" className="btn" onClick={dismissTour}>
            Got it
          </button>
        </div>
      )}
    </div>
  );
}

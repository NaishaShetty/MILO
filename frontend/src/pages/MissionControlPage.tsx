// MissionControlPage.tsx
//
// Purpose
// -------
// "What is MILO doing right now?" -- the live dashboard. Reuses
// `VisionPanel` as-is for "MILO's Eyes"/"Detected Objects" (it already
// perceives via `POST /vision/perceive` and renders camera/depth/
// object-inspector -- see that component's own docstring), `TalkToMilo`
// for text/speech input, `AgentStatusList` for "MILO Status," and
// `PlanStepsList` for "MILO's Plan" (its steps already carry live
// execution status -- `ExecutionController` updates `PlanStep.status`
// in place, so no separate progress derivation is needed). Everything
// else (current mission, location, activity feed, cancellation) reads
// directly from `TaskContext`, which is already polling the active
// task's state/events (see that context's own docstring) -- this page
// adds no polling of its own.
//
// Phase 8.2 visual pass: restructured into the mockups' 3-column grid
// (GlassCard shells, MiloCharacter status) -- every string a test
// asserts on ("No active mission.", "Status: executing", "Progress:
// 1/2 steps", "Location: kitchen — Target: user", "Cancel Mission",
// "Mission cancelled.") is unchanged; only the surrounding markup/CSS
// changed.
import { AgentStatusList } from "../components/AgentStatusList";
import { GlassCard } from "../components/GlassCard";
import { MiloCharacter } from "../components/MiloCharacter";
import type { MiloCharacterState } from "../components/MiloCharacter";
import { MiloDialogue } from "../components/MiloDialogue";
import { PlanStepsList } from "../components/PlanStepsList";
import { StatusPill } from "../components/StatusPill";
import { TalkToMilo } from "../components/TalkToMilo";
import { VisionPanel } from "../components/VisionPanel";
import { useTask } from "../state/TaskContext";
import { useVoice } from "../state/VoiceContext";
import type { TaskEvent } from "../api/tasksTypes";
import type { TaskStatus } from "../api/tasksTypes";

const QUICK_EXAMPLES = [
  "Find the apple",
  "Bring me the red mug",
  "Put the bottle on the table",
];

const STATUS_AGENTS = ["vision", "memory", "planner", "navigation", "execution", "reflection", "speech"];

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled"]);

// Real TaskStatus -> MiloCharacter state -- every mapped value is one
// of TaskState.status's actual enum members (backend/agents/
// task_state.py::TaskStatus); nothing here is invented.
const CHARACTER_STATE_FOR_STATUS: Record<TaskStatus, MiloCharacterState> = {
  created: "initializing",
  parsing: "understanding",
  retrieving_memory: "thinking",
  planning: "planning",
  executing: "executing",
  reflecting: "reflecting",
  replanning: "replanning",
  succeeded: "success",
  failed: "error",
  cancelled: "idle",
};

function formatTimestamp(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toLocaleTimeString();
}

function EventRow({ event }: { event: TaskEvent }) {
  return (
    <li className="mission-control__event">
      <span className="mission-control__event-time">{formatTimestamp(event.timestamp)}</span>
      <span className="mission-control__event-agent">{event.agent}</span>
      <span className="mission-control__event-name">{event.event}</span>
    </li>
  );
}

export function MissionControlPage() {
  const { activeTask, activeTaskId, events, cancelActive, cancelling } = useTask();
  const voice = useVoice();

  const isActive = activeTask !== null && !TERMINAL_STATUSES.has(activeTask.status);
  // `voice.state === "speaking"` overrides the task-derived state --
  // both are real (the task's own status, and whether MILO is
  // currently actually playing real synthesized audio for it).
  const characterState: MiloCharacterState =
    voice.state === "speaking" ? "speaking" : activeTask ? CHARACTER_STATE_FOR_STATUS[activeTask.status] : "idle";

  return (
    <main aria-label="Mission Control" className="mission-control">
      <h1>Mission Control</h1>

      <div className="mission-control__grid">
        <GlassCard title="MILO's Eyes" className="mission-control__eyes">
          <section aria-label="MILO's Eyes">
            <VisionPanel />
          </section>
        </GlassCard>

        <GlassCard title="Talk to MILO" className="mission-control__talk">
          <TalkToMilo quickExamples={QUICK_EXAMPLES} inputLabel="Instruction for MILO" />
        </GlassCard>

        <div className="mission-control__side">
          <GlassCard title="Current Mission" className="mission-control__mission">
            <section aria-label="Current Mission">
              {!activeTaskId && <p>No active mission.</p>}
              {activeTask && (
                <div className="mission-control__mission-card">
                  <p className="mission-control__mission-request">{activeTask.user_request}</p>
                  <StatusPill tone={isActive ? "accent" : "neutral"}>
                    Status: {activeTask.status}
                  </StatusPill>
                  {activeTask.current_plan && (
                    <p className="mission-control__mission-progress">
                      Progress: {activeTask.completed_steps.length}/{activeTask.current_plan.steps.length}{" "}
                      steps
                    </p>
                  )}
                  {isActive && (
                    <button
                      type="button"
                      className="mission-control__cancel"
                      onClick={() => void cancelActive()}
                      disabled={cancelling}
                    >
                      {cancelling ? "Cancelling..." : "Cancel Mission"}
                    </button>
                  )}
                  {activeTask.status === "cancelled" && (
                    <p className="mission-control__cancelled" role="status">
                      Mission cancelled.
                    </p>
                  )}
                </div>
              )}
            </section>
          </GlassCard>

          <GlassCard title="MILO Status" className="mission-control__status">
            <section aria-label="MILO Status" className="mission-control__status-body">
              <MiloCharacter state={characterState} size="sm" />
              <AgentStatusList names={STATUS_AGENTS} />
            </section>
            {voice.spokenText && (
              <MiloDialogue
                text={voice.spokenText}
                caption={voice.state === "speaking" ? "Speaking..." : undefined}
                className="mission-control__dialogue"
              />
            )}
          </GlassCard>
        </div>

        <GlassCard title="MILO's Plan" className="mission-control__plan">
          <section aria-label="MILO's Plan">
            {activeTask?.current_plan ? (
              <PlanStepsList steps={activeTask.current_plan.steps} />
            ) : (
              <p>No plan yet.</p>
            )}
          </section>
        </GlassCard>

        <GlassCard title="Where Is MILO?" className="mission-control__location">
          <section aria-label="Where Is MILO?">
            {activeTask?.current_location || activeTask?.target ? (
              <p>
                {activeTask.current_location ? `Location: ${activeTask.current_location}` : "Location: unknown"}
                {activeTask.target ? ` — Target: ${activeTask.target}` : ""}
              </p>
            ) : (
              <p>Location not yet known.</p>
            )}
          </section>
        </GlassCard>

        <GlassCard title="Activity Feed" className="mission-control__activity">
          <section aria-label="Activity Feed">
            {events.length === 0 ? (
              <p>No activity yet.</p>
            ) : (
              <ul className="mission-control__events">
                {events.map((event) => (
                  <EventRow key={event.event_id} event={event} />
                ))}
              </ul>
            )}
          </section>
        </GlassCard>
      </div>
    </main>
  );
}

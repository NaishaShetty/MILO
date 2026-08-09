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
import { AgentStatusList } from "../components/AgentStatusList";
import { PlanStepsList } from "../components/PlanStepsList";
import { TalkToMilo } from "../components/TalkToMilo";
import { VisionPanel } from "../components/VisionPanel";
import { useTask } from "../state/TaskContext";
import type { TaskEvent } from "../api/tasksTypes";

const QUICK_EXAMPLES = [
  "Find the apple",
  "Bring me the red mug",
  "Put the bottle on the table",
];

const STATUS_AGENTS = ["vision", "memory", "planner", "navigation", "execution", "reflection", "speech"];

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled"]);

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

  const isActive = activeTask !== null && !TERMINAL_STATUSES.has(activeTask.status);

  return (
    <main aria-label="Mission Control" className="mission-control">
      <h1>🎮 Mission Control</h1>

      <section aria-label="MILO's Eyes" className="mission-control__section">
        <h2>MILO's Eyes</h2>
        <VisionPanel />
      </section>

      <TalkToMilo quickExamples={QUICK_EXAMPLES} inputLabel="Instruction for MILO" />

      <section aria-label="Current Mission" className="mission-control__section">
        <h2>Current Mission</h2>
        {!activeTaskId && <p>No active mission.</p>}
        {activeTask && (
          <div className="mission-control__mission-card">
            <p className="mission-control__mission-request">{activeTask.user_request}</p>
            <p className="mission-control__mission-status">Status: {activeTask.status}</p>
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

      <section aria-label="MILO Status" className="mission-control__section">
        <h2>MILO Status</h2>
        <AgentStatusList names={STATUS_AGENTS} />
      </section>

      <section aria-label="MILO's Plan" className="mission-control__section">
        <h2>MILO's Plan</h2>
        {activeTask?.current_plan ? (
          <PlanStepsList steps={activeTask.current_plan.steps} />
        ) : (
          <p>No plan yet.</p>
        )}
      </section>

      <section aria-label="Where Is MILO?" className="mission-control__section">
        <h2>Where Is MILO?</h2>
        {activeTask?.current_location || activeTask?.target ? (
          <p>
            {activeTask.current_location ? `Location: ${activeTask.current_location}` : "Location: unknown"}
            {activeTask.target ? ` — Target: ${activeTask.target}` : ""}
          </p>
        ) : (
          <p>Location not yet known.</p>
        )}
      </section>

      <section aria-label="Activity Feed" className="mission-control__section">
        <h2>Activity Feed</h2>
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
    </main>
  );
}

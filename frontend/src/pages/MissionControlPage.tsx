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
// (GlassCard shells, MiloCharacter status). Later "visual refinement"
// pass: rebuilt the grid into the reference dashboard's asymmetric
// composition (camera-dominant top row, dense secondary rows) and
// added a "Detected Objects" strip fed by VisionPanel's own
// `onObjectsChange` mirror -- no second perceive() call site. Every
// string a test asserts on ("No active mission.", "Status: executing",
// "Progress: 1/2 steps", "Location: kitchen — Target: user", "Cancel
// Mission", "Mission cancelled.", "PLAN_CREATED", step descriptions,
// "Active") is unchanged; only the surrounding markup/CSS changed.
import { useState } from "react";

import { AgentArchitectureDiagram } from "../components/AgentArchitectureDiagram";
import { AgentStatusList } from "../components/AgentStatusList";
import { DetectedObjectsStrip } from "../components/DetectedObjectsStrip";
import { GlassCard } from "../components/GlassCard";
import { MiloAvatar } from "../components/MiloAvatar";
import { MiloDialogue } from "../components/MiloDialogue";
import { MiloStateIndicator } from "../components/MiloStateIndicator";
import { PlanTimeline } from "../components/PlanTimeline";
import { RobotMiniMap } from "../components/RobotMiniMap";
import { RobotStatePanel } from "../components/RobotStatePanel";
import { StatusPill } from "../components/StatusPill";
import { TalkToMilo } from "../components/TalkToMilo";
import { TaskMemoryPanel } from "../components/TaskMemoryPanel";
import { VisionPanel } from "../components/VisionPanel";
import { useMiloState } from "../state/MiloStateContext";
import { useTask } from "../state/TaskContext";
import { useVoice } from "../state/VoiceContext";
import type { TaskEvent } from "../api/tasksTypes";
import type { SpatialObject } from "../api/visionTypes";

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

function EventRow({ event, isLatest }: { event: TaskEvent; isLatest: boolean }) {
  return (
    <li className={"mission-control__event" + (isLatest ? " mission-control__event--latest" : "")}>
      <span className="mission-control__event-node" aria-hidden="true" />
      <span className="mission-control__event-time">{formatTimestamp(event.timestamp)}</span>
      <span className="mission-control__event-body">
        <span className="mission-control__event-name">{event.event}</span>
        <span className="mission-control__event-agent">{event.agent}</span>
      </span>
    </li>
  );
}

export function MissionControlPage() {
  const {
    activeTask,
    activeTaskId,
    events,
    cancelActive,
    cancelling,
    robotState,
    robotStateStatus,
    robotStateError,
  } = useTask();
  const voice = useVoice();
  // The one canonical MILO state (Phase 8.3) -- already combines the
  // active task's real status, ElevenLabs playback, and mic capture;
  // this page no longer derives its own copy of that mapping.
  const miloState = useMiloState();
  // Mirrored out of VisionPanel's own perceive() state (see that
  // component's `onObjectsChange` docstring) so the "Detected Objects"
  // strip can live as its own panel without a second vision fetch.
  const [detectedObjects, setDetectedObjects] = useState<SpatialObject[] | null>(null);

  const isActive = activeTask !== null && !TERMINAL_STATUSES.has(activeTask.status);
  const robotPosition = robotState?.position
    ? { x: robotState.position.x, z: robotState.position.z }
    : null;
  const latestEventId = events.length > 0 ? events[events.length - 1].event_id : null;

  return (
    <main aria-label="Mission Control" className="mission-control">
      <h1 className="sr-only">Mission Control</h1>

      <div className="mission-control__grid">
        <GlassCard title="MILO's Eyes" className="mission-control__eyes">
          <section aria-label="MILO's Eyes">
            <VisionPanel robotPosition={robotPosition} onObjectsChange={setDetectedObjects} />
          </section>
        </GlassCard>

        <GlassCard title="Talk to MILO" className="mission-control__talk">
          <TalkToMilo quickExamples={QUICK_EXAMPLES} inputLabel="Instruction for MILO" />
        </GlassCard>

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
                  <>
                    <p className="mission-control__mission-progress">
                      Progress: {activeTask.completed_steps.length}/{activeTask.current_plan.steps.length}{" "}
                      steps
                    </p>
                    <div className="mission-control__mission-bar" aria-hidden="true">
                      <div
                        className="mission-control__mission-bar-fill"
                        style={{
                          width: `${
                            activeTask.current_plan.steps.length === 0
                              ? 0
                              : (activeTask.completed_steps.length / activeTask.current_plan.steps.length) *
                                100
                          }%`,
                        }}
                      />
                    </div>
                  </>
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
            <MiloAvatar state={miloState} size="md" />
            <MiloStateIndicator state={miloState} />
          </section>
          <AgentStatusList names={STATUS_AGENTS} />
          {voice.spokenText && (
            <MiloDialogue
              text={voice.spokenText}
              caption={voice.state === "speaking" ? "Speaking..." : undefined}
              className="mission-control__dialogue"
            />
          )}
        </GlassCard>

        <GlassCard
          title="Detected Objects"
          titleAction={detectedObjects && detectedObjects.length > 0 ? `${detectedObjects.length} Objects` : undefined}
          className="mission-control__objects"
        >
          <section aria-label="Detected Objects">
            <DetectedObjectsStrip objects={detectedObjects} />
          </section>
        </GlassCard>

        <GlassCard title="MILO's Plan" className="mission-control__plan">
          <section aria-label="MILO's Plan">
            {activeTask?.current_plan ? (
              <PlanTimeline
                steps={activeTask.current_plan.steps}
                executionHistory={activeTask.execution_history}
              />
            ) : (
              <p>No plan yet.</p>
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
                  <EventRow key={event.event_id} event={event} isLatest={event.event_id === latestEventId} />
                ))}
              </ul>
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
            <RobotMiniMap position={robotPosition} size="lg" className="mission-control__location-map" />
            <RobotStatePanel
              robotState={robotState}
              status={robotStateStatus}
              error={robotStateError}
            />
          </section>
        </GlassCard>

        <GlassCard title="Agent Architecture" className="mission-control__agents mission-control__agents--secondary">
          <section aria-label="Agent Architecture">
            <AgentArchitectureDiagram />
          </section>
        </GlassCard>

        <GlassCard title="Memory for this Task" className="mission-control__memory mission-control__memory--secondary">
          <section aria-label="Memory for this Task">
            <TaskMemoryPanel taskId={activeTaskId} />
          </section>
        </GlassCard>
      </div>
    </main>
  );
}

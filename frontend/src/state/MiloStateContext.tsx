// MiloStateContext.tsx
//
// Purpose
// -------
// Phase 8.3's central MILO state machine. Every other piece of
// real-time MILO state already exists (the active task's `TaskStatus`
// in `TaskContext`, ElevenLabs playback in `VoiceContext`, mic capture
// in `SpeechContext`, backend reachability in `AgentsContext`) -- this
// context is not a new data source, it is the single place that
// combines all of them into one canonical `MiloState` (see
// `miloState.ts`), so `MiloAvatar`/`MiloStateIndicator` instances
// across the app render the same state without each page
// re-deriving its own mapping (the Phase 8.3 brief's explicit
// requirement: "Do NOT let individual pages manage MILO state
// independently").
//
// Precedence (highest first) -- every input is real, never invented:
//   1. `voice.state === "speaking"`      -- MILO is audibly speaking.
//   2. `speech.state` (mic capture)      -- listening/understanding.
//   3. `cancelling`                      -- a real cancel request is in flight.
//   4. success/error hold                -- see below.
//   5. `activeTask.status`, refined by the current plan step's real
//      `action` while executing          -- the task lifecycle.
//   6. `agents` connectivity              -- offline/idle fallback.
//
// Success/error are transient the way the SUCCESS/ERROR reference
// images imply ("allow the state to remain visible briefly, transition
// naturally back to idle" / "after the error is acknowledged... return
// to the appropriate state"): once a task lands on succeeded/failed,
// this holds that state for a few seconds (or until the next task
// starts, if sooner) and then reverts to idle -- a real timer over a
// real terminal status, not a fabricated one.
//
// Finer-than-status execution states (Phase 8.7): the backend's
// `TaskStatus` enum has one flat "executing" value, but the currently
// executing step's real `action` (`backend/planner/actions.py`'s
// registry: "navigate", "locate", "pickup", "open", "close", "place",
// "put_down", "generic_act") is already on the wire via
// `activeTask.current_plan.steps[activeTask.current_step]` -- so
// "navigating" (action === "navigate") and "perceiving" (action ===
// "locate") are derived from that real field instead of collapsing
// every execution step into the same generic "executing" visual.
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { ApiError } from "../api/client";
import type { TaskState, TaskStatus } from "../api/tasksTypes";
import { TERMINAL_TASK_STATUSES } from "../api/tasksTypes";
import { useAgents } from "./AgentsContext";
import { useSpeech } from "./SpeechContext";
import { useTask } from "./TaskContext";
import { useVoice } from "./VoiceContext";
import type { MiloState } from "./miloState";

const SUCCESS_HOLD_MS = 4000;
const ERROR_HOLD_MS = 6000;

// Real TaskStatus -> MiloState -- every mapped value is one of
// TaskState.status's actual enum members (backend/agents/
// task_state.py::TaskStatus); nothing here is invented. "executing" is
// the fallback for a step whose action isn't navigate/locate --
// `stateForExecutingTask` below refines it further using the real
// current step.
const STATE_FOR_TASK_STATUS: Record<TaskStatus, MiloState> = {
  created: "initializing",
  parsing: "understanding",
  retrieving_memory: "recalling_memory",
  planning: "planning",
  executing: "executing",
  reflecting: "reflecting",
  replanning: "replanning",
  succeeded: "success",
  failed: "error",
  cancelled: "idle",
};

// Action names that map to a dedicated MiloState -- the rest of
// `actions.ACTION_REGISTRY` (pickup/open/close/place/put_down/
// generic_act) all render as the generic "executing" state, since
// none of them have a visually distinct meaning the way "moving
// through the environment" (navigate) or "looking for something"
// (locate) do.
const STATE_FOR_STEP_ACTION: Record<string, MiloState> = {
  navigate: "navigating",
  locate: "perceiving",
};

function stateForExecutingTask(task: TaskState): MiloState {
  const step =
    task.current_plan && task.current_step != null ? task.current_plan.steps[task.current_step] : null;
  return (step && STATE_FOR_STEP_ACTION[step.action]) || "executing";
}

export interface MiloStateContextValue {
  state: MiloState;
}

const MiloStateContext = createContext<MiloStateContextValue | null>(null);

export function MiloStateProvider({ children }: { children: ReactNode }) {
  const { activeTask, activeTaskId, cancelling } = useTask();
  const voice = useVoice();
  const speech = useSpeech();
  const { status: agentsStatus, error: agentsError } = useAgents();

  // Mirrors NavBar.tsx's `deriveConnectionState`: a 503
  // `agents_unavailable` means "backend reachable, no orchestrator
  // running yet" (a normal, common dev mode), not a disconnect -- only
  // a real network failure counts as truly offline.
  const isOffline =
    agentsStatus === "error" &&
    !(agentsError instanceof ApiError && agentsError.category === "agents_unavailable");

  const taskStatus = activeTask?.status ?? null;
  const [holding, setHolding] = useState<{ status: "succeeded" | "failed"; taskId: string } | null>(
    null,
  );

  useEffect(() => {
    if (!activeTaskId || !taskStatus) return;
    if (taskStatus !== "succeeded" && taskStatus !== "failed") return;
    setHolding({ status: taskStatus, taskId: activeTaskId });
    const holdMs = taskStatus === "succeeded" ? SUCCESS_HOLD_MS : ERROR_HOLD_MS;
    const timer = window.setTimeout(() => {
      setHolding((current) => (current?.taskId === activeTaskId ? null : current));
    }, holdMs);
    return () => window.clearTimeout(timer);
  }, [activeTaskId, taskStatus]);

  const state: MiloState = useMemo(() => {
    if (voice.state === "speaking") return "speaking";
    if (speech.state === "listening") return "listening";
    if (speech.state === "processing" || speech.state === "transcribing") return "understanding";
    if (cancelling) return "pausing";

    if (holding && holding.taskId === activeTaskId) {
      return holding.status === "succeeded" ? "success" : "error";
    }

    if (activeTask && !TERMINAL_TASK_STATUSES.includes(activeTask.status)) {
      return activeTask.status === "executing"
        ? stateForExecutingTask(activeTask)
        : STATE_FOR_TASK_STATUS[activeTask.status];
    }

    if (isOffline) return "offline";
    if (agentsStatus === "loading" || agentsStatus === "idle") return "initializing";
    return "idle";
  }, [voice.state, speech.state, cancelling, holding, activeTaskId, activeTask, isOffline, agentsStatus]);

  const value = useMemo<MiloStateContextValue>(() => ({ state }), [state]);

  return <MiloStateContext.Provider value={value}>{children}</MiloStateContext.Provider>;
}

export function useMiloState(): MiloState {
  const context = useContext(MiloStateContext);
  if (!context) {
    throw new Error("useMiloState() must be used within a <MiloStateProvider>.");
  }
  return context.state;
}

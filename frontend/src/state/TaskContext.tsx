// TaskContext.tsx
//
// Purpose
// -------
// Global "current mission" state: which task the user is actively
// watching, its live `TaskState` and event log, and the single shared path
// both text and speech input use to create a task (`submitInstruction`) --
// see `tasks.ts`'s module docstring on why there must be exactly one
// task-creation call site. Also exposes `history` (every task this backend
// has run, via `useTaskHistory`) so pages don't each open a second,
// redundant request loop for the same data.
//
// Live updates are pushed, not polled: `useLiveTask` opens a server-sent
// event stream for the active task (state + events in ONE connection) and
// only falls back to polling if the stream cannot be used. That replaced
// the separate 1 s task poll and 1.5 s events poll this context used to
// run.
//
// Not every request becomes a task: MILO may answer a question, remember a
// preference, ask for a missing detail, or say it can't do something. Those
// replies arrive as `lastReply` (and `submitInstruction` resolves with
// them) so the UI can show them in MILO's speech bubble without a task.
//
// On mount, if nothing has been explicitly selected yet and the most
// recently created task in `history` is still in flight, this adopts it as
// the active task -- so reloading mid-task keeps showing live progress.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { TaskContext } from "./useTask";
import type { ReactNode } from "react";

import { ApiError } from "../api/client";
import { cancelTask, createTask, getTaskRobotState } from "../api/tasks";
import type {
  CreateTaskResult,
  InputSource,
  PlannerChoice,
  RobotState,
  TaskEvent,
  TaskState, ReplyChoice } from "../api/tasksTypes";
import { TERMINAL_TASK_STATUSES } from "../api/tasksTypes";
import type { LiveTransport } from "../hooks/useLiveTask";
import { useLiveTask } from "../hooks/useLiveTask";
import type { PollingStatus } from "../hooks/usePolling";
import { usePolling } from "../hooks/usePolling";
import { useTaskHistory } from "../hooks/useTaskHistory";

const ROBOT_POLL_INTERVAL_MS = 2000;

/** A reply from MILO that did not start a task: shown in the speech bubble. */
export interface MiloReply {
  kind: "answer" | "remembered" | "not_remembered" | "clarify" | "unsupported";
  text: string;
  /** Tappable answers to a question back ("which cup?"). */
  choices?: ReplyChoice[];
}

export interface TaskContextValue {
  activeTaskId: string | null;
  activeTask: TaskState | null;
  activeTaskStatus: PollingStatus;
  activeTaskError: unknown;
  /** `sse` while pushed by the backend, `polling` if the stream could not be used. */
  transport: LiveTransport;
  events: TaskEvent[];
  history: TaskState[];
  historyStatus: PollingStatus;
  refreshHistory: () => void;
  setActiveTaskId: (taskId: string | null) => void;
  submitInstruction: (
    instruction: string,
    inputSource?: InputSource,
    planner?: PlannerChoice,
    objectId?: string,
  ) => Promise<CreateTaskResult>;
  submitting: boolean;
  submitError: string | null;
  /** MILO's latest non-task reply (an answer, a question back, ...), until the next request. */
  lastReply: MiloReply | null;
  clearReply: () => void;
  cancelActive: () => Promise<void>;
  cancelling: boolean;
  /** `null` while loading or once the simulator reports unavailable -- see `robotStateStatus`/`robotStateError`. */
  robotState: RobotState | null;
  robotStateStatus: PollingStatus;
  robotStateError: unknown;
}

function replyFrom(result: CreateTaskResult): MiloReply | null {
  switch (result.kind) {
    case "task":
      return null;
    case "answer":
      return { kind: "answer", text: result.answer };
    case "clarify":
    case "unsupported":
      return { kind: result.kind, text: result.message, choices: result.choices };
    default:
      return { kind: result.kind, text: result.message };
  }
}

export function TaskProvider({ children }: { children: ReactNode }) {
  const [activeTaskId, setActiveTaskIdState] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [lastReply, setLastReply] = useState<MiloReply | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const hasBootstrapped = useRef(false);

  const { tasks: history, status: historyStatus, refresh: refreshHistory } = useTaskHistory();

  useEffect(() => {
    if (hasBootstrapped.current) return;
    if (historyStatus !== "success") return;
    hasBootstrapped.current = true;
    const newest = history[0];
    if (newest && !TERMINAL_TASK_STATUSES.includes(newest.status)) {
      setActiveTaskIdState(newest.task_id);
    }
  }, [history, historyStatus]);

  const live = useLiveTask(activeTaskId);

  // The history list (Recent missions) must show a finished task's final
  // state: refresh it once when the active task reaches a terminal status.
  const activeStatus = live.task?.status ?? null;
  const refreshedFor = useRef<string | null>(null);
  useEffect(() => {
    if (activeTaskId === null || activeStatus === null) return;
    if (!TERMINAL_TASK_STATUSES.includes(activeStatus)) return;
    const key = `${activeTaskId}:${activeStatus}`;
    if (refreshedFor.current === key) return;
    refreshedFor.current = key;
    refreshHistory();
  }, [activeTaskId, activeStatus, refreshHistory]);

  const robotStateFetcher = useCallback(() => {
    if (!activeTaskId) return Promise.reject(new Error("no active task"));
    return getTaskRobotState(activeTaskId);
  }, [activeTaskId]);

  // Kept polling through terminal status too -- the simulator's live pose
  // is still meaningful to show right after a task finishes. A 503 here (no
  // simulator) surfaces as `robotStateStatus === "error"`; callers should
  // render "simulator not connected" -- never fabricate a pose.
  const robotStatePoll = usePolling(robotStateFetcher, {
    intervalMs: ROBOT_POLL_INTERVAL_MS,
    enabled: activeTaskId !== null,
  });

  function setActiveTaskId(taskId: string | null) {
    hasBootstrapped.current = true;
    setActiveTaskIdState(taskId);
  }

  async function submitInstruction(
    instruction: string,
    inputSource: InputSource = "text",
    planner?: PlannerChoice,
    objectId?: string,
  ): Promise<CreateTaskResult> {
    // Context-level re-entrancy guard: two overlapping calls must never
    // both reach the backend, whatever the UI does.
    if (submitting) {
      throw new Error("A task submission is already in progress.");
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      const result =
        planner || objectId
          ? await createTask(instruction, inputSource, planner, objectId)
          : await createTask(instruction, inputSource);
      if (result.kind === "task") {
        setLastReply(null);
        setActiveTaskId(result.task_id);
        refreshHistory();
      } else {
        setLastReply(replyFrom(result));
      }
      return result;
    } catch (error) {
      setSubmitError(
        error instanceof ApiError
          ? error.message
          : "I couldn't reach MILO's server. Check that it's running and try again.",
      );
      throw error;
    } finally {
      setSubmitting(false);
    }
  }

  async function cancelActive(): Promise<void> {
    if (!activeTaskId) return;
    setCancelling(true);
    try {
      await cancelTask(activeTaskId);
    } catch {
      // Best-effort from the UI's perspective -- the live stream reflects
      // whatever the backend actually did.
    } finally {
      setCancelling(false);
      live.refresh();
    }
  }

  const value = useMemo<TaskContextValue>(
    () => ({
      activeTaskId,
      activeTask: live.task,
      activeTaskStatus: live.status,
      activeTaskError: live.error,
      transport: live.transport,
      events: live.events,
      history,
      historyStatus,
      refreshHistory,
      setActiveTaskId,
      submitInstruction,
      submitting,
      submitError,
      lastReply,
      clearReply: () => setLastReply(null),
      cancelActive,
      cancelling,
      robotState: robotStatePoll.data,
      robotStateStatus: robotStatePoll.status,
      robotStateError: robotStatePoll.error,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      activeTaskId,
      live.task,
      live.status,
      live.error,
      live.transport,
      live.events,
      history,
      historyStatus,
      submitting,
      submitError,
      lastReply,
      cancelling,
      robotStatePoll.data,
      robotStatePoll.status,
      robotStatePoll.error,
    ],
  );

  return <TaskContext.Provider value={value}>{children}</TaskContext.Provider>;
}

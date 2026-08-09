// TaskContext.tsx
//
// Purpose
// -------
// Global "current mission" state: which task the user is actively
// watching, its live `TaskState` (polled), its event log (polled), and
// the single shared path both text and speech input use to create a
// task (`submitInstruction`) -- see `tasks.ts`'s module docstring on
// why there must be exactly one task-creation call site. Also exposes
// `history` (every task this backend has run, via `useTaskHistory`) so
// Home/Mission Control don't each open a second, redundant polling
// loop for the same data.
//
// On mount, if nothing has been explicitly selected yet and the most
// recently created task in `history` is still in flight, this adopts
// it as the active task -- so reloading Mission Control mid-task keeps
// showing live progress instead of a blank "no active mission" state.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";

import { ApiError } from "../api/client";
import { cancelTask, createTask, getTask, getTaskEvents } from "../api/tasks";
import type { InputSource, TaskEvent, TaskState } from "../api/tasksTypes";
import { TERMINAL_TASK_STATUSES } from "../api/tasksTypes";
import { useTaskHistory } from "../hooks/useTaskHistory";
import type { PollingStatus } from "../hooks/usePolling";
import { usePolling } from "../hooks/usePolling";

const TASK_POLL_INTERVAL_MS = 1000;
const EVENTS_POLL_INTERVAL_MS = 1500;

export interface TaskContextValue {
  activeTaskId: string | null;
  activeTask: TaskState | null;
  activeTaskStatus: PollingStatus;
  activeTaskError: unknown;
  events: TaskEvent[];
  history: TaskState[];
  historyStatus: PollingStatus;
  refreshHistory: () => void;
  setActiveTaskId: (taskId: string | null) => void;
  submitInstruction: (instruction: string, inputSource?: InputSource) => Promise<TaskState>;
  submitting: boolean;
  submitError: string | null;
  cancelActive: () => Promise<void>;
  cancelling: boolean;
}

const TaskContext = createContext<TaskContextValue | null>(null);

export function TaskProvider({ children }: { children: ReactNode }) {
  const [activeTaskId, setActiveTaskIdState] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
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

  const taskFetcher = useCallback(() => {
    if (!activeTaskId) return Promise.reject(new Error("no active task"));
    return getTask(activeTaskId);
  }, [activeTaskId]);

  const taskPoll = usePolling(taskFetcher, {
    intervalMs: TASK_POLL_INTERVAL_MS,
    enabled: activeTaskId !== null,
    isTerminal: (state) => TERMINAL_TASK_STATUSES.includes(state.status),
  });

  const isActiveTerminal =
    taskPoll.data !== null && TERMINAL_TASK_STATUSES.includes(taskPoll.data.status);

  const eventsFetcher = useCallback(() => {
    if (!activeTaskId) return Promise.reject(new Error("no active task"));
    return getTaskEvents(activeTaskId);
  }, [activeTaskId]);

  const eventsPoll = usePolling(eventsFetcher, {
    intervalMs: EVENTS_POLL_INTERVAL_MS,
    enabled: activeTaskId !== null && !isActiveTerminal,
  });

  function setActiveTaskId(taskId: string | null) {
    hasBootstrapped.current = true;
    setActiveTaskIdState(taskId);
  }

  async function submitInstruction(
    instruction: string,
    inputSource: InputSource = "text",
  ): Promise<TaskState> {
    setSubmitting(true);
    setSubmitError(null);
    try {
      const state = await createTask(instruction, inputSource);
      setActiveTaskId(state.task_id);
      refreshHistory();
      return state;
    } catch (error) {
      setSubmitError(
        error instanceof ApiError
          ? error.message
          : "Could not reach MILO's backend. Please try again.",
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
      // Best-effort from the UI's perspective -- the next poll tick
      // reflects whatever the backend actually did.
    } finally {
      setCancelling(false);
      taskPoll.refresh();
    }
  }

  const value = useMemo<TaskContextValue>(
    () => ({
      activeTaskId,
      activeTask: taskPoll.data,
      activeTaskStatus: taskPoll.status,
      activeTaskError: taskPoll.error,
      events: eventsPoll.data ?? [],
      history,
      historyStatus,
      refreshHistory,
      setActiveTaskId,
      submitInstruction,
      submitting,
      submitError,
      cancelActive,
      cancelling,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      activeTaskId,
      taskPoll.data,
      taskPoll.status,
      taskPoll.error,
      eventsPoll.data,
      history,
      historyStatus,
      submitting,
      submitError,
      cancelling,
    ],
  );

  return <TaskContext.Provider value={value}>{children}</TaskContext.Provider>;
}

export function useTask(): TaskContextValue {
  const context = useContext(TaskContext);
  if (!context) {
    throw new Error("useTask() must be used within a <TaskProvider>.");
  }
  return context;
}

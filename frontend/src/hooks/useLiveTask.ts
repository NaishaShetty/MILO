// useLiveTask.ts
//
// Purpose
// -------
// One task's live state and events, pushed by the backend over server-sent
// events (`api/stream.ts`) instead of polled -- falling back to the old
// polling transport (`usePolling`) if the stream cannot be used: no
// `EventSource` in this environment, the connection fails, or it drops
// before the task finished. The fallback is per task id and sticky for that
// task (no flapping); selecting another task tries SSE again.
//
// `transport` says which one is live, so the UI/tests can tell.
import { useCallback, useEffect, useState } from "react";

import { openTaskStream, streamingSupported } from "../api/stream";
import { getTask, getTaskEvents } from "../api/tasks";
import type { TaskEvent, TaskState } from "../api/tasksTypes";
import { TERMINAL_TASK_STATUSES } from "../api/tasksTypes";
import type { PollingStatus } from "./usePolling";
import { usePolling } from "./usePolling";

export type LiveTransport = "idle" | "connecting" | "sse" | "polling";

const TASK_POLL_INTERVAL_MS = 1000;
const EVENTS_POLL_INTERVAL_MS = 1500;

export interface LiveTask {
  task: TaskState | null;
  events: TaskEvent[];
  transport: LiveTransport;
  status: PollingStatus;
  error: unknown;
  /** Re-reads the task now (only meaningful on the polling transport). */
  refresh: () => void;
}

function isTerminal(task: TaskState | null): boolean {
  return task !== null && TERMINAL_TASK_STATUSES.includes(task.status);
}

export function useLiveTask(taskId: string | null): LiveTask {
  const [streamTask, setStreamTask] = useState<TaskState | null>(null);
  const [streamEvents, setStreamEvents] = useState<TaskEvent[]>([]);
  const [transport, setTransport] = useState<LiveTransport>("idle");
  const [streamError, setStreamError] = useState<unknown>(null);

  useEffect(() => {
    setStreamTask(null);
    setStreamEvents([]);
    setStreamError(null);

    if (taskId === null) {
      setTransport("idle");
      return;
    }
    if (!streamingSupported()) {
      setTransport("polling");
      return;
    }

    setTransport("connecting");
    return openTaskStream(taskId, {
      onState: (state) => {
        setStreamTask(state);
        setTransport("sse");
      },
      onEvent: (event) =>
        setStreamEvents((previous) =>
          previous.some((existing) => existing.event_id === event.event_id)
            ? previous
            : [...previous, event],
        ),
      onError: (error) => {
        setStreamError(error);
        setTransport("polling");
      },
    });
  }, [taskId]);

  const polling = transport === "polling" && taskId !== null;

  const taskFetcher = useCallback(() => getTask(taskId as string), [taskId]);
  const taskPoll = usePolling(taskFetcher, {
    intervalMs: TASK_POLL_INTERVAL_MS,
    enabled: polling,
    isTerminal: (state) => TERMINAL_TASK_STATUSES.includes(state.status),
  });

  const eventsFetcher = useCallback(() => getTaskEvents(taskId as string), [taskId]);
  const eventsPoll = usePolling(eventsFetcher, {
    intervalMs: EVENTS_POLL_INTERVAL_MS,
    enabled: polling && !isTerminal(taskPoll.data),
  });

  if (transport === "polling") {
    return {
      // Prefer the freshest of what the stream last delivered and the poll.
      task: taskPoll.data ?? streamTask,
      events: eventsPoll.data ?? streamEvents,
      transport,
      status: taskPoll.status,
      error: taskPoll.error ?? streamError,
      refresh: taskPoll.refresh,
    };
  }

  return {
    task: streamTask,
    events: streamEvents,
    transport,
    status: taskId === null ? "idle" : streamTask ? "success" : "loading",
    error: streamError,
    refresh: () => undefined,
  };
}

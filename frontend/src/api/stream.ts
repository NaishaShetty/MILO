// stream.ts
//
// Purpose
// -------
// Server-sent-event clients for `GET /api/v1/tasks/{id}/stream` (one task's
// state + events) and `GET /api/v1/tasks/stream` (a snapshot of every task).
// They replace the 1-1.5 s polling loops: the backend pushes a `state`
// event whenever the task changes and a `task_event` per new orchestrator
// event, then closes with an `end` event once the task is over.
//
// Failure is part of the contract. `EventSource` reconnects on its own, but
// a stream that cannot connect at all (a proxy that buffers it, an auth
// error, an old backend) should not leave the UI blank -- so on any error
// this closes the connection and calls `onError` exactly once, and the
// caller (`useLiveTask`) switches to polling. An `end` event is a clean
// finish and never reaches `onError`.
import { withApiKey } from "./client";
import type { TaskEvent, TaskState, TaskSummary } from "./tasksTypes";

export interface TaskStreamHandlers {
  onState: (state: TaskState) => void;
  onEvent?: (event: TaskEvent) => void;
  /** The task reached a terminal status; the stream closes itself. */
  onEnd?: () => void;
  /** The stream failed; it is already closed. Called at most once. */
  onError: (error: unknown) => void;
}

export type CloseStream = () => void;

function parse<T>(message: MessageEvent): T | null {
  try {
    return JSON.parse(message.data as string) as T;
  } catch {
    return null;
  }
}

/** True when this environment has `EventSource` at all (jsdom does not). */
export function streamingSupported(): boolean {
  return typeof EventSource !== "undefined";
}

export function openTaskStream(taskId: string, handlers: TaskStreamHandlers): CloseStream {
  const source = new EventSource(
    withApiKey(`/api/v1/tasks/${encodeURIComponent(taskId)}/stream`),
  );
  let finished = false;

  const finish = () => {
    finished = true;
    source.close();
  };

  source.addEventListener("state", (message) => {
    const state = parse<TaskState>(message as MessageEvent);
    if (state) handlers.onState(state);
  });
  source.addEventListener("task_event", (message) => {
    const event = parse<TaskEvent>(message as MessageEvent);
    if (event) handlers.onEvent?.(event);
  });
  source.addEventListener("end", () => {
    finish();
    handlers.onEnd?.();
  });
  source.onerror = (error) => {
    if (finished) return;
    finish();
    handlers.onError(error);
  };

  return () => {
    finished = true;
    source.close();
  };
}

export interface TasksStreamHandlers {
  onSnapshot: (tasks: TaskSummary[]) => void;
  onError: (error: unknown) => void;
}

export function openTasksStream(handlers: TasksStreamHandlers): CloseStream {
  const source = new EventSource(withApiKey("/api/v1/tasks/stream"));
  let finished = false;
  source.addEventListener("snapshot", (message) => {
    const tasks = parse<TaskSummary[]>(message as MessageEvent);
    if (tasks) handlers.onSnapshot(tasks);
  });
  source.onerror = (error) => {
    if (finished) return;
    finished = true;
    source.close();
    handlers.onError(error);
  };
  return () => {
    finished = true;
    source.close();
  };
}

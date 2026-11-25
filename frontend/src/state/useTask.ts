// useTask.ts -- the TaskContext context object and its hook, kept out of TaskContext.tsx so that
// file only exports components (React Fast Refresh needs that).
import { createContext, useContext } from "react";

import type { TaskContextValue } from "./TaskContext";

export const TaskContext = createContext<TaskContextValue | null>(null);

export function useTask(): TaskContextValue {
  const context = useContext(TaskContext);
  if (!context) {
    throw new Error("useTask() must be used within a <TaskProvider>.");
  }
  return context;
}

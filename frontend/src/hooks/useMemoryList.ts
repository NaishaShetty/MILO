// useMemoryList.ts
//
// Purpose
// -------
// Shared "everything MILO has stored in memory" data source, built on
// `GET /api/v1/memory` (Phase 8.2 -- see `backend/api/routes/
// memory.py`). Mirrors `useTaskHistory.ts`'s polling shape exactly.
// Unlike the earlier task-derived aggregation (`utils/memory.ts`),
// this reads the real, persistent memory store directly -- memories
// from every task ever run, not just ones this browser session has
// polled into `TaskContext.history`.
import { useCallback } from "react";

import { listMemory } from "../api/memory";
import type { MemoryListResponse } from "../api/memoryTypes";
import { usePolling } from "./usePolling";

const POLL_INTERVAL_MS = 5000;

export interface MemoryListResult {
  memories: MemoryListResponse["memories"];
  countsByType: MemoryListResponse["counts_by_type"];
  status: "idle" | "loading" | "success" | "error";
  error: unknown;
  refresh: () => void;
}

export function useMemoryList(enabled = true): MemoryListResult {
  const fetcher = useCallback(() => listMemory(), []);
  const { data, status, error, refresh } = usePolling(fetcher, {
    intervalMs: POLL_INTERVAL_MS,
    enabled,
  });
  return {
    memories: data?.memories ?? [],
    countsByType: data?.counts_by_type ?? {},
    status,
    error,
    refresh,
  };
}

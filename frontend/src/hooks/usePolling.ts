// usePolling.ts
//
// Purpose
// -------
// Shared polling primitive, extracted from the self-scheduling
// `setTimeout` pattern `ExecutionPanel.tsx`/`VisionPanel.tsx`/
// `PlannerPanel.tsx` each implement independently today (see Session 3
// audit notes). A `setTimeout`-reschedule loop (not `setInterval`) so a
// slow response never causes overlapping requests -- the next poll is
// only scheduled once the previous one has resolved. No websocket/SSE
// transport exists on the backend for task/agent state (see
// `backend/api/routes/tasks.py`'s docstring: `POST /tasks` backgrounds
// the run and callers "poll GET /tasks/{id} for progress"), so a
// simple interval is this project's real-time mechanism, per spec Part
// "REAL-TIME / POLLING": "If real-time infrastructure does not already
// exist, implement reliable polling rather than overengineering a new
// transport."
import { useEffect, useRef, useState } from "react";

export type PollingStatus = "idle" | "loading" | "success" | "error";

export interface PollingResult<T> {
  data: T | null;
  error: unknown;
  status: PollingStatus;
  /** Re-fetches immediately, outside the normal interval. */
  refresh: () => void;
}

export interface UsePollingOptions<T> {
  /** Milliseconds between the end of one fetch and the start of the next. */
  intervalMs: number;
  /** When false, no fetch happens (existing data/error is left as-is). */
  enabled: boolean;
  /** When it returns true for the latest data, polling stops until re-enabled. */
  isTerminal?: (data: T) => boolean;
}

/**
 * Polls `fetcher` on a self-rescheduling interval while `enabled`, and
 * stops once `isTerminal(data)` is true. `fetcher`/`isTerminal` are
 * read from a ref on every tick (not `useEffect` dependencies) so
 * callers can pass fresh closures every render without restarting the
 * loop -- only `intervalMs`/`enabled` changing does that.
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  { intervalMs, enabled, isTerminal }: UsePollingOptions<T>,
): PollingResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [status, setStatus] = useState<PollingStatus>("idle");

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const isTerminalRef = useRef(isTerminal);
  isTerminalRef.current = isTerminal;

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Bumped whenever a run should stop scheduling further ticks (unmount,
  // `enabled`/`intervalMs` change, or a manual `refresh()`) -- every
  // in-flight/scheduled tick checks it still matches before touching
  // state or scheduling the next one, so a stale run can never race a
  // newer one.
  const generationRef = useRef(0);

  function runTick(generation: number, intervalMsForRun: number) {
    (async () => {
      setStatus((previous) => (previous === "idle" ? "loading" : previous));
      try {
        const result = await fetcherRef.current();
        if (generation !== generationRef.current) return;
        setData(result);
        setError(null);
        setStatus("success");
        if (isTerminalRef.current?.(result)) return;
      } catch (err) {
        if (generation !== generationRef.current) return;
        setError(err);
        setStatus("error");
      }
      if (generation === generationRef.current) {
        timerRef.current = setTimeout(
          () => runTick(generation, intervalMsForRun),
          intervalMsForRun,
        );
      }
    })();
  }

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    generationRef.current += 1;

    if (!enabled) {
      setStatus("idle");
      return;
    }

    runTick(generationRef.current, intervalMs);

    return () => {
      generationRef.current += 1;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, intervalMs]);

  function refresh() {
    if (timerRef.current) clearTimeout(timerRef.current);
    generationRef.current += 1;
    if (enabled) {
      runTick(generationRef.current, intervalMs);
    }
  }

  return { data, error, status, refresh };
}

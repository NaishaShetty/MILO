// usePolling.test.ts
//
// Purpose
// -------
// Unit tests for the shared polling hook: it fetches immediately, then
// reschedules on the given interval, stops once `isTerminal` fires,
// tolerates fetch errors without crashing, and supports a manual
// `refresh()`. Uses real timers + `waitFor` for "did it eventually
// settle" assertions and fake timers (advanced manually, never mixed
// with `waitFor`, which itself polls via a timer) for "did it wait for
// the interval" assertions.
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePolling } from "./usePolling";

describe("usePolling (real timers)", () => {
  it("fetches immediately and exposes the result", async () => {
    const fetcher = vi.fn().mockResolvedValue({ n: 1 });
    const { result } = renderHook(() => usePolling(fetcher, { intervalMs: 1000, enabled: true }));

    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(result.current.data).toEqual({ n: 1 });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("does not fetch while disabled", async () => {
    const fetcher = vi.fn().mockResolvedValue({ n: 1 });
    const { result } = renderHook(() => usePolling(fetcher, { intervalMs: 1000, enabled: false }));

    expect(result.current.status).toBe("idle");
    await new Promise((resolve) => setTimeout(resolve, 10));
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("surfaces a rejected fetch as an error without throwing", async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error("network down"));
    const { result } = renderHook(() => usePolling(fetcher, { intervalMs: 1000, enabled: true }));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toBeInstanceOf(Error);
  });
});

describe("usePolling (fake timers)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("reschedules after intervalMs and stops at isTerminal", async () => {
    let n = 0;
    const fetcher = vi.fn<() => Promise<{ n: number }>>().mockImplementation(async () => ({ n: ++n }));
    const { result } = renderHook(() =>
      usePolling(fetcher, { intervalMs: 1000, enabled: true, isTerminal: (d) => d.n >= 2 }),
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data).toEqual({ n: 1 });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(result.current.data).toEqual({ n: 2 });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    // isTerminal fired at n=2 -- no further calls should have happened.
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("refresh() re-fetches immediately, outside the interval", async () => {
    const fetcher = vi.fn().mockResolvedValue({ n: 1 });
    const { result } = renderHook(() => usePolling(fetcher, { intervalMs: 5000, enabled: true }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);

    await act(async () => {
      result.current.refresh();
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});

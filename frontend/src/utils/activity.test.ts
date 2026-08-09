// activity.test.ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { exportEventsAsJson, filterByCategory, searchEvents } from "./activity";
import type { TaskEvent } from "../api/tasksTypes";

function event(overrides: Partial<TaskEvent>): TaskEvent {
  return {
    event_id: "e1",
    task_id: "t1",
    agent: "orchestrator",
    event: "TASK_CREATED",
    timestamp: 1000,
    payload: {},
    latency_ms: null,
    ...overrides,
  };
}

describe("filterByCategory", () => {
  const events = [
    event({ event_id: "e1", event: "TASK_CREATED" }),
    event({ event_id: "e2", event: "PLAN_CREATED" }),
    event({ event_id: "e3", event: "ACTION_FAILED" }),
  ];

  it("returns everything for 'all'", () => {
    expect(filterByCategory(events, "all")).toHaveLength(3);
  });

  it("filters to only the category's event types", () => {
    expect(filterByCategory(events, "planning").map((e) => e.event_id)).toEqual(["e2"]);
  });

  it("errors category matches ACTION_FAILED and TASK_FAILED", () => {
    expect(filterByCategory(events, "errors").map((e) => e.event_id)).toEqual(["e3"]);
  });

  it("returns everything for an unknown category id", () => {
    expect(filterByCategory(events, "nonexistent")).toHaveLength(3);
  });
});

describe("searchEvents", () => {
  const events = [
    event({ event_id: "e1", agent: "orchestrator", event: "TASK_CREATED", payload: { goal: "find" } }),
    event({ event_id: "e2", task_id: "t2", event: "PLAN_CREATED" }),
  ];

  it("matches on event type", () => {
    expect(searchEvents(events, "plan_created")).toEqual([events[1]]);
  });

  it("matches on task_id", () => {
    expect(searchEvents(events, "t2")).toEqual([events[1]]);
  });

  it("matches on payload contents", () => {
    expect(searchEvents(events, "find")).toEqual([events[0]]);
  });

  it("returns everything for a blank query", () => {
    expect(searchEvents(events, "   ")).toEqual(events);
  });
});

describe("exportEventsAsJson", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("creates a downloadable JSON blob and clicks a link", () => {
    const createObjectURL = vi.fn().mockReturnValue("blob:mock");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    exportEventsAsJson([event({})]);

    expect(createObjectURL).toHaveBeenCalled();
    expect(clickSpy).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock");
  });
});

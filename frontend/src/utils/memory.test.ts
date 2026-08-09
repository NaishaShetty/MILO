// memory.test.ts
import { describe, expect, it } from "vitest";

import { aggregateMemories, countsByType, semanticKnowledge } from "./memory";
import type { TaskState } from "../api/tasksTypes";

function task(overrides: Partial<TaskState>): TaskState {
  return {
    task_id: "t",
    user_request: "",
    input_source: "text",
    goal: null,
    objects: [],
    target: null,
    current_location: null,
    current_plan: null,
    current_step: null,
    observations: [],
    known_objects: [],
    completed_steps: [],
    execution_history: [],
    failures: [],
    retrieved_memories: [],
    agent_states: {},
    status: "succeeded",
    latencies_ms: {},
    created_memories: [],
    metrics: { actions: 0, failures: 0, replans: 0, attempts: 0, success: true, total_ms: null },
    ...overrides,
  };
}

describe("aggregateMemories", () => {
  it("flattens created/retrieved memories across tasks", () => {
    const history = [
      task({
        task_id: "t2",
        created_memories: [{ memory_id: "m2", memory_type: "episodic", content: "found the mug" }],
      }),
      task({
        task_id: "t1",
        retrieved_memories: [{ memory_id: "m1", memory_type: "semantic", content: "kitchen has a fridge" }],
      }),
    ];

    const result = aggregateMemories(history);

    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({ memory_id: "m2", task_id: "t2", source: "created" });
    expect(result[1]).toMatchObject({ memory_id: "m1", task_id: "t1", source: "retrieved" });
  });

  it("de-duplicates the same memory_id seen more than once", () => {
    const history = [
      task({
        task_id: "t2",
        retrieved_memories: [{ memory_id: "m1", memory_type: "semantic", content: "x" }],
      }),
      task({
        task_id: "t1",
        created_memories: [{ memory_id: "m1", memory_type: "semantic", content: "x" }],
      }),
    ];

    expect(aggregateMemories(history)).toHaveLength(1);
  });

  it("returns an empty array for no history", () => {
    expect(aggregateMemories([])).toEqual([]);
  });
});

describe("countsByType", () => {
  it("counts entries per memory_type", () => {
    const entries = aggregateMemories([
      task({
        task_id: "t1",
        created_memories: [
          { memory_id: "m1", memory_type: "semantic", content: "a" },
          { memory_id: "m2", memory_type: "failure", content: "b" },
        ],
        retrieved_memories: [{ memory_id: "m3", memory_type: "semantic", content: "c" }],
      }),
    ]);

    expect(countsByType(entries)).toEqual({ semantic: 2, failure: 1 });
  });

  it("groups entries with no memory_type under 'unknown'", () => {
    const entries = aggregateMemories([
      task({ task_id: "t1", created_memories: [{ memory_id: "m1", content: "a" }] }),
    ]);
    expect(countsByType(entries)).toEqual({ unknown: 1 });
  });
});

describe("semanticKnowledge", () => {
  it("returns only semantic-type entries", () => {
    const entries = aggregateMemories([
      task({
        task_id: "t1",
        created_memories: [
          { memory_id: "m1", memory_type: "semantic", content: "kitchen has a fridge" },
          { memory_id: "m2", memory_type: "episodic", content: "picked up the mug" },
        ],
      }),
    ]);

    const knowledge = semanticKnowledge(entries);
    expect(knowledge).toHaveLength(1);
    expect(knowledge[0].content).toBe("kitchen has a fridge");
  });
});

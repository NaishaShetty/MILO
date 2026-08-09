// agents.test.ts
//
// Purpose
// -------
// Unit tests for the centralized Agents API client.
import { afterEach, describe, expect, it, vi } from "vitest";

import { getAgentStatus, listAgents } from "./agents";

function mockFetchOnce(status: number, body: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
      text: async () => JSON.stringify(body),
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("listAgents", () => {
  it("GETs the agent list", async () => {
    const body = [{ name: "vision", state: "idle" }];
    mockFetchOnce(200, body);
    await expect(listAgents()).resolves.toEqual(body);
    expect(fetch).toHaveBeenCalledWith("/api/v1/agents", expect.objectContaining({}));
  });

  it("throws ApiError when the registry isn't available", async () => {
    mockFetchOnce(503, { category: "agents_unavailable", message: "No orchestrator." });
    await expect(listAgents()).rejects.toMatchObject({ status: 503, category: "agents_unavailable" });
  });
});

describe("getAgentStatus", () => {
  it("GETs one agent's status", async () => {
    mockFetchOnce(200, { name: "planner", state: "thinking" });
    await getAgentStatus("planner");
    expect(fetch).toHaveBeenCalledWith("/api/v1/agents/planner/status", expect.objectContaining({}));
  });

  it("throws ApiError on 404 for an unregistered agent", async () => {
    mockFetchOnce(404, { category: "agent_not_found", message: "No such agent." });
    await expect(getAgentStatus("nope")).rejects.toMatchObject({ status: 404 });
  });
});

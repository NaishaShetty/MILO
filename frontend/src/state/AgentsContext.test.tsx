// AgentsContext.test.tsx
import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AgentsProvider, useAgents } from "./AgentsContext";
import * as agentsApi from "../api/agents";

vi.mock("../api/agents", async () => {
  const actual = await vi.importActual<typeof import("../api/agents")>("../api/agents");
  return { ...actual, listAgents: vi.fn() };
});

describe("AgentsContext", () => {
  it("exposes the agent list once loaded", async () => {
    vi.mocked(agentsApi.listAgents).mockResolvedValue([{ name: "vision", state: "idle" }]);

    const { result } = renderHook(() => useAgents(), { wrapper: AgentsProvider });

    await waitFor(() => expect(result.current.status).toBe("success"));
    expect(result.current.agents).toEqual([{ name: "vision", state: "idle" }]);
  });

  it("surfaces an unavailable registry as an error state, not a crash", async () => {
    const { ApiError } = await import("../api/client");
    vi.mocked(agentsApi.listAgents).mockRejectedValue(
      new ApiError(503, { category: "agents_unavailable", message: "No orchestrator." }),
    );

    const { result } = renderHook(() => useAgents(), { wrapper: AgentsProvider });

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.agents).toEqual([]);
  });

  it("throws a clear error when used outside the provider", () => {
    const { result } = renderHook(() => {
      try {
        return useAgents();
      } catch (error) {
        return error;
      }
    });
    expect(result.current).toBeInstanceOf(Error);
  });
});

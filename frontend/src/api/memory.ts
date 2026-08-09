// memory.ts
//
// Purpose
// -------
// The *only* place in this frontend that issues an HTTP request to the
// Phase 8.2 Memory API (`backend/api/routes/memory.py`) -- mirrors
// `tasks.ts`'s "centralized API client per domain" convention. Real
// memory search/listing, replacing the earlier fake-task workaround
// (see git history / `utils/memory.ts`'s superseded docstring): this
// backend route did not exist before Phase 8.2.

import { ApiError, request } from "./client";
import type { MemoryListResponse, MemorySearchResponse, MemoryType } from "./memoryTypes";

export { ApiError as MemoryApiError };

/** `GET /api/v1/memory/search?q=...` -- real ranked retrieval via MemoryAgent. */
export async function searchMemory(query: string, topK = 10): Promise<MemorySearchResponse> {
  const params = new URLSearchParams({ q: query, top_k: String(topK) });
  return request<MemorySearchResponse>(`/api/v1/memory/search?${params.toString()}`);
}

/** `GET /api/v1/memory` -- unranked listing (newest first) + real counts by type. */
export async function listMemory(memoryType?: MemoryType, limit = 200): Promise<MemoryListResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (memoryType) {
    params.set("memory_type", memoryType);
  }
  return request<MemoryListResponse>(`/api/v1/memory?${params.toString()}`);
}

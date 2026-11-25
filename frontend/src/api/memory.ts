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
import type {
  Memory,
  MemoryListResponse,
  MemorySearchResponse,
  MemoryType,
} from "./memoryTypes";

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

/** `POST /api/v1/memory/{id}/forget` -- archives the memory so MILO stops using it. */
export async function forgetMemory(memoryId: string): Promise<Memory> {
  return request<Memory>(`/api/v1/memory/${encodeURIComponent(memoryId)}/forget`, {
    method: "POST",
  });
}

/** `PATCH /api/v1/memory/{id}` -- fix the place / text, pin, or set aside for review. */
export async function editMemory(
  memoryId: string,
  change: { place?: string; content?: string; pinned?: boolean; quarantined?: boolean },
): Promise<Memory> {
  return request<Memory>(`/api/v1/memory/${encodeURIComponent(memoryId)}`, {
    method: "PATCH",
    body: JSON.stringify(change),
  });
}

/** `DELETE /api/v1/memory/{id}` -- remove it for good. */
export async function deleteMemory(memoryId: string): Promise<void> {
  await request(`/api/v1/memory/${encodeURIComponent(memoryId)}`, { method: "DELETE" });
}

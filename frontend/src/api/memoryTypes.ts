// memoryTypes.ts
//
// Purpose
// -------
// TypeScript types for the Phase 8.2 Memory API (`GET /api/v1/memory`,
// `GET /api/v1/memory/search`) served by `backend/api/routes/memory.py`.
// Mirrors `backend/memory/models.py`'s `Memory` and
// `backend/api/models/memory.py`'s response envelopes field-for-field.

// Mirrors `backend/memory/models.py`'s `MemoryType`.
export type MemoryType = "semantic" | "episodic" | "failure" | "user";

// Mirrors `backend/memory/models.py`'s `MemoryProvenance`.
export type MemoryProvenance = "observation" | "execution" | "user_input" | "inference" | "reflection" | "system";

// Mirrors `backend/memory/models.py`'s `MemoryStatus`.
export type MemoryStatusValue = "active" | "archived";

export interface Memory {
  memory_id: string;
  memory_type: MemoryType;
  content: string;
  provenance: MemoryProvenance;
  status: MemoryStatusValue;
  confidence: number;
  created_at: number;
  observed_at: number | null;
  updated_at: number;
  episode_id: string | null;
  task_id: string | null;
  metadata: Record<string, unknown>;
}

export interface MemorySearchResult {
  memory: Memory;
  similarity: number;
  final_score: number;
  ranking_components: Record<string, number>;
}

export interface MemorySearchResponse {
  query: string;
  results: MemorySearchResult[];
}

export interface MemoryListResponse {
  memories: Memory[];
  counts_by_type: Record<string, number>;
}

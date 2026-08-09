// memory.ts (frontend/src/utils)
//
// Purpose
// -------
// Shared label vocabulary for the Memory page's four categories.
// `MemoryPage.tsx` reads real data directly from the Phase 8.2 Memory
// API (`api/memory.ts`, `hooks/useMemoryList.ts`,
// `backend/api/routes/memory.py`) -- this file previously also held
// client-side aggregation helpers (`aggregateMemories`/`countsByType`/
// `semanticKnowledge`) for a fake-task-based workaround that predated
// that real endpoint; those are removed now that the workaround is
// gone (see git history), not left as orphaned dead code.
export const MEMORY_CATEGORY_LABELS: Record<string, string> = {
  semantic: "Things I Know",
  episodic: "Experiences",
  failure: "Things That Went Wrong",
  user: "Your Preferences",
};

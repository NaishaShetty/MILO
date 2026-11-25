// observability.ts -- mission traces (replay), stage timings and the scene map.
import { ApiError, getApiKey, request } from "./client";

export interface TraceRecord {
  seq: number;
  ts: number;
  kind: string;
  step_id: number | null;
  data: Record<string, unknown>;
}

export interface MissionSummary {
  mission_id: string;
  task_text: string | null;
  planner: string | null;
  started_at: number;
  ended_at: number | null;
  outcome: string | null;
}

export interface Trace {
  mission: MissionSummary & {
    reason?: string | null;
    latencies?: Record<string, number> | null;
    verification?: Array<{ text: string; ok: boolean; reason?: string }> | null;
  };
  records: TraceRecord[];
}

export interface StageStat {
  p50: number | null;
  p95: number | null;
  n: number;
}

export interface Bar {
  label: string;
  kind: string;
  status?: string;
  start_ms: number;
  ms: number;
}

export interface SceneMap {
  agent: { x: number; z: number } | null;
  path: Array<{ x: number; z: number; yaw: number }>;
  objects: Array<{ id: string; type: string; x: number | null; z: number | null; visible: boolean; in: string[] }>;
  beliefs: Array<{ object: string; place: string; confidence: number; last_seen: number; source: string }>;
  has_positions: boolean;
}

export const listTraces = (limit = 30) =>
  request<{ missions: MissionSummary[] }>(`/api/v1/traces?limit=${limit}`).then((r) => r.missions);
export const getTrace = (id: string) => request<Trace>(`/api/v1/traces/${encodeURIComponent(id)}`);
export const getTraceStats = () =>
  request<{ missions: number; stages: Record<string, StageStat>; actions: Record<string, StageStat> }>("/api/v1/traces/stats");
export const getWaterfall = (id: string) =>
  request<{ bars: Bar[] }>(`/api/v1/traces/${encodeURIComponent(id)}/waterfall`).then((r) => r.bars);
export const getSceneMap = () => request<SceneMap>("/api/v1/scene/map");

/** Downloads the one-page Markdown run report. */
export async function downloadReport(id: string): Promise<void> {
  const key = getApiKey();
  const response = await fetch(`/api/v1/traces/${encodeURIComponent(id)}/report`, {
    headers: key ? { "X-API-Key": key } : {},
  });
  if (!response.ok) throw new ApiError(response.status, { category: "report", message: "I couldn't make that report." });
  const url = URL.createObjectURL(new Blob([await response.text()], { type: "text/markdown" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `milo-run-${id.slice(0, 8)}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

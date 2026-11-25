// benchmark.ts -- the latest benchmark report and its history (GET /api/v1/benchmark).
import { request } from "./client";
import { demoJson, isDemo } from "./demo";

export type Pct = number | null;
export interface PlannerScore {
  known: { success: Pct };
  novel: { success: Pct };
  faults: { success: Pct };
  all: { steps: number | null; sim_s: number | null; replans: number | null };
  recovery_by_fault: Record<string, Pct>;
}
export interface Report {
  subset: string;
  provider: string;
  planners: Record<string, PlannerScore>;
  ablations?: Record<string, Record<string, unknown>>;
  seconds: number;
}
export interface HistoryLine {
  date: string;
  commit: string;
  subset: string;
  planners: Record<string, { known: Pct; novel: Pct; faults: Pct }>;
}

export async function getBenchmark(): Promise<{ latest: Report | null; history: HistoryLine[] }> {
  if (isDemo()) {
    const latest = await demoJson<Report>("benchmark.json").catch(() => null);
    const text = await fetch("/demo/history.jsonl").then((r) => (r.ok ? r.text() : "")).catch(() => "");
    const history = text.split("\n").filter(Boolean).map((line) => JSON.parse(line) as HistoryLine);
    return { latest, history };
  }
  return request("/api/v1/benchmark");
}


// ObservabilityPanel.tsx -- Lab: where the time goes. p50 / p95 per stage over recent
// missions, and a waterfall of the latest mission (plan, each step, each reflection).
import { useEffect, useState } from "react";

import { getTraceStats, getWaterfall, listTraces } from "../api/observability";
import type { Bar, StageStat } from "../api/observability";

const STAGE_LABEL: Record<string, string> = {
  planning_ms: "Planning",
  vision_ms: "Looking",
  execution_ms: "Doing",
  reflection_ms: "Reflecting",
  memory_retrieval_ms: "Remembering",
  memory_write_ms: "Writing memories",
  total_ms: "Whole mission",
};

const ms = (v: number | null) => (v === null ? "–" : v >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v)} ms`);

export function ObservabilityPanel() {
  const [stages, setStages] = useState<Record<string, StageStat> | null>(null);
  const [count, setCount] = useState(0);
  const [bars, setBars] = useState<Bar[]>([]);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const stats = await getTraceStats();
        const latest = (await listTraces(1))[0];
        const waterfall = latest ? await getWaterfall(latest.mission_id) : [];
        if (!live) return;
        setStages(stats.stages);
        setCount(stats.missions);
        setBars(waterfall);
        setProblem(null);
      } catch {
        if (live) setProblem("I couldn't load the timings. Is MILO's server running?");
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 3000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, []);

  const end = Math.max(1, ...bars.map((b) => b.start_ms + b.ms));
  return (
    <section className="card" aria-label="Where the time goes">
      <h2>Where the time goes</h2>
      {problem && <div className="notice notice--error" role="alert">{problem}</div>}
      {stages && !Object.values(stages).some((s) => s.n > 0) && (
        <p className="muted">No missions recorded yet. Timings appear here after MILO's first job.</p>
      )}
      {stages && Object.values(stages).some((s) => s.n > 0) && (
        <table aria-label="Stage timings">
          <thead>
            <tr>
              <th>Stage</th>
              <th>Typical (p50)</th>
              <th>Slowest 5% (p95)</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(stages)
              .filter(([, s]) => s.n > 0)
              .map(([name, s]) => (
                <tr key={name}>
                  <td>{STAGE_LABEL[name] ?? name}</td>
                  <td>{ms(s.p50)}</td>
                  <td>{ms(s.p95)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      )}
      <p className="muted">Over the last {count} missions.</p>
      {bars.length > 0 && (
        <div className="waterfall" role="list" aria-label="Latest mission waterfall">
          {bars.map((b, i) => (
            <div key={i} role="listitem" className="waterfall__row" title={`${b.label}: ${ms(b.ms)}`}>
              <span className="waterfall__label">{b.label}</span>
              <span className="waterfall__track">
                <span
                  className={`waterfall__bar waterfall__bar--${b.kind}${b.status === "failed" ? " waterfall__bar--failed" : ""}`}
                  style={{ left: `${(b.start_ms / end) * 100}%`, width: `${Math.max(0.5, (b.ms / end) * 100)}%` }}
                />
              </span>
              <span className="muted">{ms(b.ms)}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

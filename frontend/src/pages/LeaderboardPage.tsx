// LeaderboardPage.tsx -- the latest benchmark: every planner on the fixed suite, recovery
// from injected faults, what each part of MILO is worth (ablations), and the trend.
import { useEffect, useState } from "react";

import { getBenchmark } from "../api/benchmark";
import type { HistoryLine, Pct, Report } from "../api/benchmark";

const pct = (v: Pct | undefined) => (v === null || v === undefined ? "not run" : `${Math.round(v * 100)}%`);

/** A tiny trend line of one planner's success under faults, oldest to newest. */
function Trend({ points }: { points: number[] }) {
  if (points.length < 2) return <span className="muted">one run so far</span>;
  const w = 120;
  const h = 28;
  const d = points.map((p, i) => `${(i / (points.length - 1)) * w},${h - p * h}`).join(" ");
  return (
    <svg width={w} height={h} role="img" aria-label={`trend over ${points.length} runs`}>
      <polyline points={d} fill="none" stroke="var(--tangerine)" strokeWidth="2" />
    </svg>
  );
}

export function LeaderboardPage() {
  const [data, setData] = useState<{ latest: Report | null; history: HistoryLine[] } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    getBenchmark()
      .then(setData)
      .catch(() => setProblem("I couldn't load the benchmark. Is MILO's server running?"));
  }, []);
  const latest = data?.latest;
  const full = (data?.history ?? []).filter((h) => h.subset === "full");
  return (
    <div className="legacy-page">
      <section className="card">
        <h1>Leaderboard</h1>
        <p className="muted">
          How each planner does on MILO's fixed benchmark: the same tasks, rooms, faults and seeds every time.
          Run it with <code>make benchmark</code>.
        </p>
        {problem && <div className="notice notice--error" role="alert">{problem}</div>}
        {data && !latest && <p>No results yet. Run the benchmark to fill this in.</p>}
        {latest && (
          <table aria-label="Planner results">
            <thead>
              <tr>
                <th>Planner</th>
                <th>Known tasks</th>
                <th>New tasks</th>
                <th>Under faults</th>
                <th>Steps</th>
                <th>Trend (faults)</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(latest.planners).map(([name, s]) => (
                <tr key={name}>
                  <td>{name.replace("_", " ")}</td>
                  <td>{pct(s.known.success)}</td>
                  <td>{pct(s.novel.success)}</td>
                  <td>{pct(s.faults.success)}</td>
                  <td>{s.all.steps ?? "–"}</td>
                  <td>
                    <Trend points={full.map((h) => h.planners[name]?.faults).filter((v): v is number => typeof v === "number")} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      {latest && (
        <section className="card">
          <h2>Getting back on track</h2>
          <p className="muted">Success when something goes wrong once or twice mid-mission.</p>
          <table aria-label="Recovery by fault">
            <thead>
              <tr>
                <th>Planner</th>
                {Object.keys(Object.values(latest.planners)[0]?.recovery_by_fault ?? {}).map((f) => (
                  <th key={f}>{f.replace(/_/g, " ")}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(latest.planners).map(([name, s]) => (
                <tr key={name}>
                  <td>{name.replace("_", " ")}</td>
                  {Object.values(s.recovery_by_fault).map((v, i) => (
                    <td key={i}>{pct(v)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      {latest?.ablations && (
        <section className="card">
          <h2>What each part is worth</h2>
          <ul aria-label="Ablations">
            {Object.entries(latest.ablations).map(([name, v]) => (
              <li key={name}>
                <strong>{name.replace(/_/g, " ")}</strong>:{" "}
                {Object.entries(v)
                  .map(([k, x]) =>
                    typeof x === "number" ? `${k} ${pct(x)}` : `${k} ${pct((x as { success: Pct }).success)}`,
                  )
                  .join(" · ")}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

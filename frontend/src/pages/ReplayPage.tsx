// ReplayPage.tsx -- drag through any past mission: the camera frame, the step, what MILO
// was thinking and its reflection verdicts at that moment. Shareable link + report export.
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { downloadReport, getTrace, listTraces } from "../api/observability";
import type { MissionSummary, Trace, TraceRecord } from "../api/observability";

function MissionList() {
  const [missions, setMissions] = useState<MissionSummary[] | null>(null);
  useEffect(() => {
    listTraces(30).then(setMissions).catch(() => setMissions([]));
  }, []);
  return (
    <section className="card">
      <h1>Replays</h1>
      <p className="muted">Pick a mission to step through what happened.</p>
      {missions?.length === 0 && <p>No recorded missions yet.</p>}
      <ul className="library" aria-label="Recorded missions">
        {missions?.map((m) => (
          <li key={m.mission_id}>
            <Link to={`/replay/${m.mission_id}`}>{m.task_text || m.mission_id}</Link>{" "}
            <span className="pill">{m.outcome ?? "running"}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ReplayPage() {
  const { missionId } = useParams();
  const [trace, setTrace] = useState<Trace | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [at, setAt] = useState(0);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!missionId) return;
    getTrace(missionId)
      .then((t) => {
        setTrace(t);
        setAt(Math.max(0, t.records.length - 1));
      })
      .catch(() => setProblem("I don't have a record of that mission."));
  }, [missionId]);

  const upTo = useMemo<TraceRecord[]>(() => (trace ? trace.records.slice(0, at + 1) : []), [trace, at]);
  if (!missionId) return <MissionList />;
  if (problem) return <div className="notice notice--error" role="alert">{problem}</div>;
  if (!trace) return <p className="muted">Loading the replay...</p>;

  const steps = upTo.filter((r) => r.kind === "step");
  const step = steps[steps.length - 1];
  const frame = [...steps].reverse().find((r) => typeof r.data.frame === "string")?.data.frame as string | undefined;
  const thoughts = upTo.filter((r) => r.kind === "thought").slice(-4);
  const verdict = [...upTo].reverse().find((r) => r.kind === "reflection");
  const plan = [...upTo].reverse().find((r) => r.kind === "plan")?.data.plan as { steps?: Array<{ step_id: number; action: string; target: string | null }> } | undefined;
  const current = trace.records[at];

  return (
    <div className="legacy-page">
      <section className="card">
        <h1>Replay: {trace.mission.task_text || trace.mission.mission_id}</h1>
        <p className="muted">
          {trace.mission.outcome ?? "still running"}
          {trace.mission.reason ? ` · ${trace.mission.reason}` : ""}
        </p>
        <label htmlFor="scrub">
          Moment {at + 1} of {trace.records.length}: <strong>{current?.kind.replace(/_/g, " ")}</strong>
        </label>
        <input
          id="scrub"
          type="range"
          min={0}
          max={Math.max(0, trace.records.length - 1)}
          value={at}
          onChange={(e) => setAt(Number(e.target.value))}
          style={{ width: "100%" }}
        />
        <div className="controls">
          <button
            type="button"
            className="btn"
            onClick={() => {
              void navigator.clipboard?.writeText(window.location.href);
              setCopied(true);
            }}
          >
            {copied ? "Link copied" : "Copy link"}
          </button>
          <button type="button" className="btn" onClick={() => void downloadReport(trace.mission.mission_id)}>
            Download report
          </button>
        </div>
      </section>
      <div className="replay">
        <section className="card" aria-label="What MILO saw">
          <h2>What MILO saw</h2>
          {frame ? (
            <img alt="MILO's camera at this moment" src={`data:image/jpeg;base64,${frame}`} style={{ width: "100%", borderRadius: 12 }} />
          ) : (
            <p className="muted">No camera frame for this moment.</p>
          )}
        </section>
        <section className="card" aria-label="The plan">
          <h2>The plan</h2>
          <ol className="steps">
            {plan?.steps?.map((s) => (
              <li key={s.step_id} aria-current={step?.step_id === s.step_id ? "step" : undefined}>
                {step?.step_id === s.step_id ? <strong>{`${s.action} ${s.target ?? ""}`}</strong> : `${s.action} ${s.target ?? ""}`}
              </li>
            ))}
          </ol>
          {step && (
            <p className="muted">
              Step {step.step_id}: {String(step.data.status)} in {Math.round(Number(step.data.duration_ms ?? 0))} ms
            </p>
          )}
        </section>
        <section className="card" aria-label="What MILO was thinking">
          <h2>What MILO was thinking</h2>
          <ul>
            {thoughts.map((t) => (
              <li key={t.seq}>{String(t.data.text)}</li>
            ))}
          </ul>
          {verdict && (
            <p>
              Reflection: <strong>{String(verdict.data.verdict)}</strong>
              {verdict.data.reason ? ` · ${String(verdict.data.reason)}` : ""}
            </p>
          )}
        </section>
      </div>
    </div>
  );
}

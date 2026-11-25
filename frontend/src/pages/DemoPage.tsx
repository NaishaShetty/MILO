// DemoPage.tsx -- the front door in demo mode: recorded missions to replay, and the
// headline results, with no backend, simulator or GPU needed.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { demoMissions } from "../api/demo";
import type { DemoMission } from "../api/demo";
import { MiloRobot } from "../components/MiloRobot";

export function DemoPage() {
  const [missions, setMissions] = useState<DemoMission[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => {
    demoMissions()
      .then(setMissions)
      .catch(() => setProblem("The recorded missions are missing. Run `python -m demo.record` to make them."));
  }, []);
  return (
    <div className="legacy-page">
      <section className="card">
        <div className="mission-head">
          <div>
            <h1>Meet MILO</h1>
            <p className="muted">
              This is demo mode: recorded missions played back, so it works without a simulator or GPU. Each replay shows
              MILO's view (a schematic sketch here), its plan, what it was thinking and how it checked its work.
            </p>
          </div>
          <MiloRobot pose="speaking" size={110} />
        </div>
        {problem && <div className="notice notice--error" role="alert">{problem}</div>}
      </section>
      <ul className="scrap-grid" aria-label="Recorded missions">
        {missions?.map((m) => (
          <li key={m.id} className="card">
            <h2>{m.title}</h2>
            <p>{m.about}</p>
            <Link className="btn btn--go" to={`/replay/${m.id}`}>
              Watch the replay
            </Link>
          </li>
        ))}
      </ul>
      <section className="card">
        <h2>How it does</h2>
        <p>
          See the <Link to="/leaderboard">Leaderboard</Link> for every planner on the fixed benchmark, recovery from faults,
          and what each part of MILO is worth.
        </p>
      </section>
    </div>
  );
}

// SceneMap.tsx -- a top-down view: MILO and the path it took this mission, where things
// really are (when the simulator gives positions), and where MILO's memory believes they
// are, with when it last saw them and how sure it is. Refreshes while a mission runs.
import { useEffect, useState } from "react";

import { getSceneMap } from "../api/observability";
import type { SceneMap as Map } from "../api/observability";
import { relativeDay } from "../utils/friendly";

const SOURCE: Record<string, string> = { user: "you told me", observation: "I saw it", skill: "worked out", imported: "imported" };

export function SceneMap({ live }: { live: boolean }) {
  const [map, setMap] = useState<Map | null>(null);
  useEffect(() => {
    let on = true;
    const load = () => getSceneMap().then((m) => on && setMap(m)).catch(() => undefined);
    load();
    const timer = live ? window.setInterval(load, 2000) : undefined;
    return () => {
      on = false;
      if (timer) window.clearInterval(timer);
    };
  }, [live]);
  if (!map) return null;

  const placed = map.objects.filter((o) => o.x !== null && o.z !== null) as Array<{ id: string; type: string; x: number; z: number; visible: boolean }>;
  const xs = [...placed.map((o) => o.x), ...map.path.map((p) => p.x), map.agent?.x ?? 0];
  const zs = [...placed.map((o) => o.z), ...map.path.map((p) => p.z), map.agent?.z ?? 0];
  const [minX, maxX, minZ, maxZ] = [Math.min(...xs), Math.max(...xs), Math.min(...zs), Math.max(...zs)];
  const sx = (x: number) => 10 + ((x - minX) / Math.max(0.1, maxX - minX)) * 280;
  const sz = (z: number) => 10 + ((maxZ - z) / Math.max(0.1, maxZ - minZ)) * 180;

  return (
    <section className="card" aria-label="Scene map">
      <h2>The room</h2>
      {map.has_positions ? (
        <svg viewBox="0 0 300 200" role="img" aria-label="Top-down map" style={{ width: "100%", maxWidth: 480 }}>
          <rect x="0" y="0" width="300" height="200" rx="12" fill="var(--cream)" stroke="var(--ink)" />
          {placed.map((o) => (
            <g key={o.id}>
              <circle cx={sx(o.x)} cy={sz(o.z)} r="4" fill={o.visible ? "var(--apricot)" : "var(--butter)"} />
              <text x={sx(o.x) + 6} y={sz(o.z) + 3} fontSize="8">{o.type}</text>
            </g>
          ))}
          {map.path.length > 1 && (
            <polyline
              points={map.path.map((p) => `${sx(p.x)},${sz(p.z)}`).join(" ")}
              fill="none"
              stroke="var(--tangerine)"
              strokeDasharray="4 3"
              strokeWidth="2"
            />
          )}
          {map.agent && <circle cx={sx(map.agent.x)} cy={sz(map.agent.z)} r="7" fill="var(--tangerine)" aria-label="MILO" />}
        </svg>
      ) : (
        <p className="muted">This simulator doesn't report positions, so here's what MILO knows instead.</p>
      )}
      <h3>Where I think things are</h3>
      {map.beliefs.length === 0 ? (
        <p className="muted">Nothing remembered yet.</p>
      ) : (
        <ul aria-label="Memory beliefs">
          {map.beliefs.slice(0, 12).map((b, i) => (
            <li key={i}>
              The <strong>{b.object}</strong> is {b.place.startsWith("in") ? "" : "at the "}
              <strong>{b.place}</strong> · {Math.round(b.confidence * 100)}% sure · {SOURCE[b.source] ?? b.source}, last seen{" "}
              {relativeDay(b.last_seen)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

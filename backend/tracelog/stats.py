"""
stats.py (backend/tracelog)

Observability over the mission trace store:

- `stage_stats(store)` -- p50 / p95 per stage (planning, observing, executing,
  reflecting, memory, total) over recent missions, plus per-action step durations;
- `waterfall(trace)` -- one mission as time bars (plan, each step, each reflection)
  relative to its start, for the Lab's waterfall view;
- `report(trace)` -- a one-page Markdown run report (what was asked, the plan, every
  step with timing, thoughts, verdicts, checks, outcome).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from tracelog.store import TraceStore

#: The stage timings the orchestrator records on every mission (`latencies_ms`).
STAGES = [
    "planning_ms",
    "vision_ms",
    "execution_ms",
    "reflection_ms",
    "memory_retrieval_ms",
    "memory_write_ms",
    "total_ms",
]


def _pct(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    i = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return round(ordered[i], 2)


def stage_stats(store: TraceStore, limit: int = 200) -> Dict[str, Any]:
    missions = store.list(limit)
    per_stage: Dict[str, List[float]] = {s: [] for s in STAGES}
    per_action: Dict[str, List[float]] = {}
    for m in missions:
        trace = store.get(m["mission_id"])
        if not trace:
            continue
        lat = trace["mission"].get("latencies") or {}
        for key, value in lat.items():
            if key in per_stage and isinstance(value, (int, float)):
                per_stage[key].append(float(value))
        for r in trace["records"]:
            if r["kind"] == "step" and r["data"].get("duration_ms") is not None:
                per_action.setdefault(r["data"]["action"], []).append(
                    float(r["data"]["duration_ms"])
                )
    return {
        "missions": len(missions),
        "stages": {
            s: {"p50": _pct(v, 0.5), "p95": _pct(v, 0.95), "n": len(v)}
            for s, v in per_stage.items()
        },
        "actions": {
            a: {"p50": _pct(v, 0.5), "p95": _pct(v, 0.95), "n": len(v)}
            for a, v in sorted(per_action.items())
        },
    }


def waterfall(trace: Dict[str, Any]) -> List[Dict[str, Any]]:
    start = trace["mission"].get("started_at") or 0.0
    bars: List[Dict[str, Any]] = []
    for r in trace["records"]:
        d = r["data"]
        if r["kind"] == "step" and d.get("started_at"):
            bars.append({
                "label": f"{d['action']} {d.get('target') or ''}".strip(),
                "kind": "step",
                "status": d.get("status"),
                "start_ms": round((d["started_at"] - start) * 1000.0, 1),
                "ms": round(d.get("duration_ms") or 0.0, 1),
            })  # fmt: skip
        elif r["kind"] in ("plan", "reflection", "replan"):
            stage = d.get("stage_ms") or {}
            key = "planning_ms" if r["kind"] != "reflection" else "reflection_ms"
            bars.append({
                "label": {"plan": "plan", "reflection": f"reflect: {d.get('verdict')}", "replan": "replan"}[r["kind"]],
                "kind": r["kind"],
                "start_ms": round((r["ts"] - start) * 1000.0, 1),
                "ms": round(float(stage.get(key, 0.0)), 1),
            })  # fmt: skip
    return bars


def report(trace: Dict[str, Any]) -> str:
    m = trace["mission"]
    lines = [f"# MILO run report: {m.get('task_text') or m['mission_id']}", ""]
    lines += [
        f"- **Outcome:** {m.get('outcome') or 'still running'}"
        + (f" ({m['reason']})" if m.get("reason") else ""),
        f"- **Planner:** {m.get('planner') or '-'}",
        f"- **Total time:** {round((m.get('latencies') or {}).get('total_ms', 0.0))} ms",
        f"- **Mission id:** `{m['mission_id']}`",
        "",
        "## Steps",
        "",
        "| # | Action | Result | Time (ms) | Confidence |",
        "|---|---|---|---|---|",
    ]
    for r in trace["records"]:
        if r["kind"] == "step":
            d = r["data"]
            conf = d.get("confidence")
            lines.append(
                f"| {r['step_id']} | {d['action']} {d.get('target') or ''} | {d.get('status')} | "
                f"{round(d.get('duration_ms') or 0)} | {'' if conf is None else f'{conf:.0%}'} |"
            )
    lines += ["", "## What MILO thought", ""]
    lines += [
        f"- {r['data'].get('text')}" for r in trace["records"] if r["kind"] == "thought"
    ]
    verdicts = [r["data"] for r in trace["records"] if r["kind"] == "reflection"]
    if verdicts:
        lines += ["", "## Reflection", ""]
        lines += [f"- {v.get('verdict')}: {v.get('reason') or ''}" for v in verdicts]
    checks = m.get("verification") or []
    if checks:
        lines += ["", "## Checks against the world", ""]
        lines += [
            f"- {'✓' if c.get('ok') else '✗'} {c.get('text')}"
            + (f" ({c['reason']})" if c.get("reason") else "")
            for c in checks
        ]
    return "\n".join(lines) + "\n"

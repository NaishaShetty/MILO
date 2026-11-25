"""
run.py (backend/benchmark)

One command, every planner, JSON + Markdown reports:

    cd backend
    python -m benchmark.run                       # full suite + ablations + faults
    python -m benchmark.run --subset ci           # the fast slice CI runs
    python -m benchmark.run --provider claude     # language-model planner = the real model

Reported per planner: success rate (the mission ended "succeeded" *and* the world-state
goal checks passed), steps run, simulated time, replans. Plus an ablation table (what
memory, reflection, replanning, in-mission recovery and skills are each worth) and a fault-recovery table
(success under each injected fault kind). Every run appends a summary line to
`benchmarks/history.jsonl` for the Leaderboard.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from agents.execution_agent import ExecutionAgentWrapper
from agents.memory_agent import MemoryAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from agents.reflection_agent import ReflectionAgent
from benchmark.suite import (
    FAULT_KINDS,
    Case,
    ci_subset,
    fault_cases,
    full_suite,
    known_cases,
    novel_cases,
)
from learning.synthetic import Faults, SyntheticSimulator
from memory.agent import MemoryAgent
from memory.config import MemoryConfig
from memory.models import MemoryProvenance
from novel.eval_novel import commands, scene
from novel.planner import NovelPlanner
from novel.providers import Provider, ScriptedProvider, build_provider
from novel.safety import Constraints
from novel.skills import SkillLibrary
from orchestration.orchestrator import Orchestrator
from planner.factory import create_planner
from schemas.task import SingleTask

PLANNERS = ["rule_based", "react", "behavior_tree", "htn", "novel"]
REPO = Path(__file__).resolve().parents[2]


class NoReflection(ReflectionAgent):
    """Ablation: never retry or replan -- the first failure ends the mission."""

    def reflect(self, record, failures, *, attempt, max_attempts, **kw):  # type: ignore[override]
        result = super().reflect(
            record, failures, attempt=attempt, max_attempts=max_attempts, **kw
        )
        if result.action in ("retry", "replan"):
            return result.model_copy(update={"action": "abort"})
        return result


@contextmanager
def _env(**values: str) -> Iterator[None]:
    old = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def reference_provider() -> ScriptedProvider:
    return ScriptedProvider({i["command"]: i["answer"] for i in commands()})


def _memory(tmp: str) -> MemoryAgent:
    agent = MemoryAgent.from_config(
        MemoryConfig(
            enabled=True,
            database_path=Path(tmp) / "m.db",
            vector_store_path=Path(tmp) / "v",
        )
    )
    objects = {o["objectId"]: o for o in scene()}
    for o in objects.values():  # true facts about where things are
        parents = o.get("parentReceptacles") or []
        if o.get("pickupable") and parents:
            agent.remember_observation(o["objectType"].lower(), "located_on", parents[0].split("|")[0].lower(),
                                       provenance=MemoryProvenance.OBSERVATION, confidence=0.9)  # fmt: skip
    return agent


def run_case(
    case: Case,
    planner: str,
    *,
    provider: Optional[Provider] = None,
    skills: Optional[SkillLibrary] = None,
    memory: bool = True,
    reflection: bool = True,
    replanning: bool = True,
    recovery: bool = True,
) -> Dict[str, Any]:
    sim = SyntheticSimulator(
        scene(),
        Faults(kind=case.fault, target=case.fault_target, times=case.fault_times),
    )
    execution = ExecutionAgentWrapper(sim)  # type: ignore[arg-type]
    novel_log = None
    with tempfile.TemporaryDirectory() as tmp:
        if planner == "novel":
            novel = NovelPlanner(provider or reference_provider(), execution.get_metadata,
                                 constraints=Constraints.load(), skills=skills or SkillLibrary(Path(tmp) / "s.db"))  # fmt: skip
            wrapper: Any = PlannerAgentWrapper(novel)  # type: ignore[arg-type]
        else:
            wrapper = PlannerAgentWrapper(create_planner(planner))
        orch = Orchestrator(
            wrapper,
            execution,
            memory_agent=MemoryAgentWrapper(_memory(tmp)) if memory else None,
            reflection_agent=None if reflection else NoReflection(),
        )
        with _env(
            MILO_GOAL_CHECK="enforce", MILO_INMISSION_RECOVERY="1" if recovery else "0"
        ):
            state = orch.run(
                SingleTask(**case.task_fields()), max_replans=2 if replanning else 0
            )
        if planner == "novel":
            novel_log = novel.log
    steps = [
        s
        for r in state.execution_history
        for s in r.step_results
        if s.status.value in ("completed", "failed", "blocked")
    ]
    return {
        "case": case.case_id,
        "kind": case.kind,
        "fault": case.fault,
        "success": state.status.value == "succeeded",
        "steps": len(steps),
        "sim_s": round(sim.clock_s, 2),
        "replans": orch._replans,
        "model_calls": novel_log.model_calls if novel_log else 0,
    }


def summarise(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = max(len(rows), 1)
    if not rows:
        return {
            "cases": 0,
            "success": None,
            "steps": None,
            "sim_s": None,
            "replans": None,
            "model_calls": None,
        }
    return {
        "cases": len(rows),
        "success": round(sum(r["success"] for r in rows) / n, 4),
        "steps": round(statistics.mean(r["steps"] for r in rows), 2) if rows else 0.0,
        "sim_s": round(statistics.mean(r["sim_s"] for r in rows), 2) if rows else 0.0,
        "replans": (
            round(statistics.mean(r["replans"] for r in rows), 3) if rows else 0.0
        ),
        "model_calls": (
            round(statistics.mean(r["model_calls"] for r in rows), 2) if rows else 0.0
        ),
    }


def run(
    subset: str = "full",
    planners: Optional[List[str]] = None,
    provider_name: str = "reference",
    ablations: bool = True,
) -> Dict[str, Any]:
    planners = planners or PLANNERS
    provider: Optional[Provider] = (
        build_provider() if provider_name == "claude" else None
    )
    cases = ci_subset() if subset == "ci" else full_suite() + fault_cases()
    started = time.time()
    report: Dict[str, Any] = {
        "subset": subset,
        "provider": provider_name,
        "planners": {},
        "by_case": {},
    }
    for planner in planners:
        # The reference plans only cover novel commands: without a real model the
        # language-model planner is run on those alone (its known/fault columns: not run).
        todo = (
            [c for c in cases if c.kind == "novel"]
            if (planner == "novel" and provider is None)
            else cases
        )
        rows = [run_case(c, planner, provider=provider) for c in todo]
        report["by_case"][planner] = rows
        report["planners"][planner] = {
            "all": summarise(rows),
            "known": summarise(
                [r for r in rows if r["kind"] == "known" and r["fault"] == "none"]
            ),
            "novel": summarise([r for r in rows if r["kind"] == "novel"]),
            "faults": summarise([r for r in rows if r["fault"] != "none"]),
            "recovery_by_fault": {
                f: summarise([r for r in rows if r["fault"] == f])["success"]
                for f in FAULT_KINDS
            },
        }
    if ablations and subset == "full":
        report["ablations"] = ablation_table(provider)
    report["seconds"] = round(time.time() - started, 1)
    return report


def ablation_table(provider: Optional[Provider]) -> Dict[str, Any]:
    """Rule-based planner on known + fault cases, novel planner on novel cases twice
    (the second pass can use skills learned in the first)."""
    known = known_cases() + fault_cases()
    novel = novel_cases()

    def known_score(
        memory: bool = True,
        reflection: bool = True,
        replanning: bool = True,
        recovery: bool = True,
    ) -> float:
        rows = [
            run_case(
                c,
                "rule_based",
                memory=memory,
                reflection=reflection,
                replanning=replanning,
                recovery=recovery,
            )
            for c in known
        ]
        return float(summarise(rows)["success"])

    def novel_score(with_skills: bool) -> Dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            shared = SkillLibrary(Path(tmp) / "s.db")
            for c in novel:  # first pass (learns skills when they are on)
                run_case(
                    c,
                    "novel",
                    provider=provider,
                    skills=shared if with_skills else None,
                )
            rows = [
                run_case(
                    c,
                    "novel",
                    provider=provider,
                    skills=shared if with_skills else None,
                )
                for c in novel
            ]
        return summarise(rows)

    full = known_score()
    out: Dict[str, Dict[str, Any]] = {
        "full": {"known+faults success": full},
        "no_memory": {"known+faults success": known_score(memory=False)},
        "no_reflection": {"known+faults success": known_score(reflection=False)},
        "no_replanning": {"known+faults success": known_score(replanning=False)},
        "no_in_mission_recovery": {"known+faults success": known_score(recovery=False)},
    }
    with_skills, without = novel_score(True), novel_score(False)
    out["full"]["novel second pass"] = {
        "success": with_skills["success"],
        "model_calls": with_skills["model_calls"],
    }
    out["no_skills"] = {
        "novel second pass": {
            "success": without["success"],
            "model_calls": without["model_calls"],
        }
    }
    return out


# -- reports ---------------------------------------------------------------------------------------


def markdown(report: Dict[str, Any]) -> str:
    lines = [
        f"# MILO benchmark ({report['subset']} suite, novel planner: {report['provider']})",
        "",
    ]
    lines += [
        "| Planner | Known | Novel | Under faults | Steps | Sim time (s) | Replans |",
        "|---|---|---|---|---|---|---|",
    ]

    def pct(v: Any) -> str:
        return "not run" if v is None else f"{v:.0%}"

    for p, s in report["planners"].items():
        lines.append(
            f"| {p} | {pct(s['known']['success'])} | {pct(s['novel']['success'])} | {pct(s['faults']['success'])} | "
            f"{s['all']['steps']} | {s['all']['sim_s']} | {s['all']['replans']} |"
        )
    lines += ["", "## Recovery by fault kind", "", "| Planner | " + " | ".join(FAULT_KINDS) + " |",
              "|---|" + "---|" * len(FAULT_KINDS)]  # fmt: skip
    for p, s in report["planners"].items():
        lines.append(
            f"| {p} | "
            + " | ".join(pct(s["recovery_by_fault"][f]) for f in FAULT_KINDS)
            + " |"
        )
    if "ablations" in report:
        a = report["ablations"]
        lines += [
            "",
            "## Ablations",
            "",
            "| Variant | Known + faults (rule-based) | Novel 2nd pass | Model calls |",
            "|---|---|---|---|",
        ]
        for name, v in a.items():
            nov = v.get("novel second pass")
            lines.append(
                f"| {name} | {v['known+faults success']:.0%} | "
                + (f"{nov['success']:.0%} | {nov['model_calls']}" if nov else "– | –")
                + " |"
                if "known+faults success" in v
                else f"| {name} | – | {nov['success']:.0%} | {nov['model_calls']} |"
            )
    lines += ["", f"Ran in {report['seconds']} s."]
    return "\n".join(lines) + "\n"


def commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except Exception:
        return "unknown"


def history_line(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "date": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "commit": commit(),
        "subset": report["subset"],
        "provider": report["provider"],
        "planners": {
            p: {k: s[k]["success"] for k in ("known", "novel", "faults")}
            for p, s in report["planners"].items()
        },
    }


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--subset", choices=["ci", "full"], default="full")
    ap.add_argument("--planners", nargs="*", default=None)
    ap.add_argument("--provider", choices=["reference", "claude"], default="reference")
    ap.add_argument("--no-ablations", action="store_true")
    ap.add_argument("--out", type=Path, default=REPO / "benchmarks" / "latest.json")
    ap.add_argument(
        "--history", type=Path, default=REPO / "benchmarks" / "history.jsonl"
    )
    a = ap.parse_args(argv)
    report = run(a.subset, a.planners, a.provider, not a.no_ablations)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2))
    a.out.with_suffix(".md").write_text(markdown(report))
    with open(a.history, "a") as fh:
        fh.write(json.dumps(history_line(report)) + "\n")
    print(markdown(report))


if __name__ == "__main__":
    main()

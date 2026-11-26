"""
run.py (backend/benchmark)

One command, every planner, JSON + Markdown reports:

    cd backend
    python -m benchmark.run                       # full suite + ablations + faults
    python -m benchmark.run --subset ci           # the fast slice CI runs
    python -m benchmark.run --provider claude     # language-model planner = the real model
    python -m benchmark.run --provider ollama --react-model qwen2.5:7b   # local models
        (MILO_OLLAMA_URL / MILO_OLLAMA_MODEL pick the server and the novel planner's model)

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
    HARD_TIERS,
    Case,
    ci_subset,
    fault_cases,
    full_suite,
    hard_cases,
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
from schemas.task import MultiTask, SingleTask

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


def case_scene(case: Case) -> List[Dict[str, Any]]:
    """The benchmark home for one case: out-of-view objects and an extra, farther
    receptacle of the same type (competing routes) when the case asks for them."""
    objects = scene()
    for o in objects:
        if o["objectType"].lower() in case.hidden:
            o["hidden"] = True
    if case.variant.startswith("second_"):
        kind = {"shelf": "Shelf", "table": "Table"}[case.variant.split("_", 1)[1]]
        objects.append({"objectId": f"{kind}|2", "objectType": kind, "distance": 6.5,
                        "visible": True, "pickupable": False})  # fmt: skip
    return objects


def _task(case: Case) -> Any:
    if case.subtasks:
        fields: List[Dict[str, Any]] = [
            {k: v for k, v in (("goal", g), ("object", o), ("target", t)) if v}
            for g, o, t in case.subtasks
        ]
        return MultiTask(subtasks=[SingleTask(**f) for f in fields])
    return SingleTask(**case.task_fields())


def _memory(
    tmp: str,
    objects_list: Optional[List[Dict[str, Any]]] = None,
    aliases: Optional[Dict[str, str]] = None,
) -> MemoryAgent:
    agent = MemoryAgent.from_config(
        MemoryConfig(
            enabled=True,
            database_path=Path(tmp) / "m.db",
            vector_store_path=Path(tmp) / "v",
        )
    )
    objects = {o["objectId"]: o for o in (objects_list or scene())}
    for o in objects.values():  # true facts about where things are
        parents = o.get("parentReceptacles") or []
        if o.get("pickupable") and parents:
            name = o["objectType"].lower()
            agent.remember_observation((aliases or {}).get(name, name), "located_on", parents[0].split("|")[0].lower(),
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
    react_client: Any = None,
) -> Dict[str, Any]:
    objects = case_scene(case)
    sim = SyntheticSimulator(
        [dict(o) for o in objects],
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
            wrapper = PlannerAgentWrapper(
                create_planner(
                    planner, llm_client=react_client if planner == "react" else None
                )
            )
        orch = Orchestrator(
            wrapper,
            execution,
            memory_agent=(
                MemoryAgentWrapper(_memory(tmp, objects, dict(case.aliases)))
                if memory
                else None
            ),
            reflection_agent=None if reflection else NoReflection(),
        )
        with _env(
            MILO_GOAL_CHECK="enforce", MILO_INMISSION_RECOVERY="1" if recovery else "0"
        ):
            state = orch.run(_task(case), max_replans=2 if replanning else 0)
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
    react_model: Optional[str] = None,
) -> Dict[str, Any]:
    planners = planners or PLANNERS
    provider: Optional[Provider] = None
    if provider_name in ("claude", "ollama"):
        with _env(MILO_NOVEL_PROVIDER=provider_name):
            provider = build_provider()
        if provider.name == "offline":
            raise SystemExit(
                f"--provider {provider_name}: no model reachable (offline)"
            )
    react_client = _local_react_client(react_model) if react_model else None
    cases = (
        ci_subset() if subset == "ci" else full_suite() + fault_cases() + hard_cases()
    )
    started = time.time()
    report: Dict[str, Any] = {
        "subset": subset,
        "provider": provider_name,
        "novel_model": getattr(provider, "model", None),
        "react_model": f"{react_model} via Ollama" if react_model else None,
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
        if planner == "react" and react_client is None:
            # Without a model ReAct falls back to rule-based: measuring it would only
            # repeat the rule-based row under another name.
            report["planners"][planner] = {
                "not_measured": "needs a model (--react-model)"
            }
            continue
        rows = [
            run_case(c, planner, provider=provider, react_client=react_client)
            for c in todo
        ]
        report["by_case"][planner] = rows
        report["planners"][planner] = {
            # The regression tier (known, novel, faults); the harder tiers are under "tiers".
            "all": summarise([r for r in rows if r["kind"] in ("known", "novel")]),
            "known": summarise(
                [r for r in rows if r["kind"] == "known" and r["fault"] == "none"]
            ),
            "novel": summarise([r for r in rows if r["kind"] == "novel"]),
            "faults": summarise(
                [r for r in rows if r["fault"] != "none" and r["kind"] == "known"]
            ),
            "recovery_by_fault": {
                f: summarise(
                    [r for r in rows if r["fault"] == f and r["kind"] == "known"]
                )["success"]
                for f in FAULT_KINDS
            },
            "tiers": {
                t: summarise([r for r in rows if r["kind"] == t]) for t in HARD_TIERS
            },
        }
    if ablations and subset == "full":
        report["ablations"] = ablation_table(provider)
    report["seconds"] = round(time.time() - started, 1)
    return report


def _local_react_client(model: str) -> Any:
    """ReAct's language-model client pointed at Ollama's OpenAI-compatible endpoint."""
    from language.config import LLMRuntimeConfig
    from language.provider_factory import create_llm_client

    url = os.environ.get("MILO_OLLAMA_URL", "http://localhost:11434").rstrip("/")
    with _env(LANGUAGE_LLM_PROVIDER="qwen", LANGUAGE_LLM_BASE_URL=f"{url}/v1",
              LANGUAGE_LLM_MODEL=model, QWEN_API_KEY="not-needed"):  # fmt: skip
        return create_llm_client(LLMRuntimeConfig.from_env())


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

    def hard_score(
        memory: bool = True,
        reflection: bool = True,
        replanning: bool = True,
        recovery: bool = True,
    ) -> Dict[str, Optional[float]]:
        rows = [
            run_case(c, "rule_based", memory=memory, reflection=reflection,
                     replanning=replanning, recovery=recovery)
            for c in hard_cases()
        ]  # fmt: skip
        return {
            t: summarise([r for r in rows if r["kind"] == t])["success"]
            for t in HARD_TIERS
        }

    full = known_score()
    out: Dict[str, Dict[str, Any]] = {
        "full": {"known+faults success": full},
        "no_memory": {"known+faults success": known_score(memory=False)},
        "no_reflection": {"known+faults success": known_score(reflection=False)},
        "no_replanning": {"known+faults success": known_score(replanning=False)},
        "no_in_mission_recovery": {"known+faults success": known_score(recovery=False)},
    }
    for name, switches in (("full", {}), ("no_memory", {"memory": False}),
                           ("no_reflection", {"reflection": False}), ("no_replanning", {"replanning": False}),
                           ("no_in_mission_recovery", {"recovery": False})):  # fmt: skip
        out[name]["hard tiers"] = hard_score(**switches)
    # The learned memory embedder instead of hashing (where a trained one exists).
    learned_dir = Path(
        os.environ.get("MEMORY_LEARNED_EMBEDDER_DIR", "artifacts/memory_embedder")
    )
    if (learned_dir / "config.json").exists():
        with _env(MEMORY_EMBEDDING_PROVIDER="learned"):
            out["learned_memory_embedder"] = {"hard tiers": hard_score()}
    else:
        out["learned_memory_embedder"] = {
            "not_available": f"no trained embedder at {learned_dir}"
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


def measured(report: Dict[str, Any]) -> Dict[str, Any]:
    """Planners that were actually run (ReAct without a model is not)."""
    return {p: s for p, s in report["planners"].items() if "not_measured" not in s}


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
        if "not_measured" in s:
            lines.append(f"| {p} | not measured ({s['not_measured']}) | | | | | |")
            continue
        lines.append(
            f"| {p} | {pct(s['known']['success'])} | {pct(s['novel']['success'])} | {pct(s['faults']['success'])} | "
            f"{s['all']['steps']} | {s['all']['sim_s']} | {s['all']['replans']} |"
        )
    lines += ["", "## Recovery by fault kind", "", "| Planner | " + " | ".join(FAULT_KINDS) + " |",
              "|---|" + "---|" * len(FAULT_KINDS)]  # fmt: skip
    for p, s in measured(report).items():
        lines.append(
            f"| {p} | "
            + " | ".join(pct(s["recovery_by_fault"][f]) for f in FAULT_KINDS)
            + " |"
        )
    lines += ["", "## Harder tiers (memory, long missions, competing routes)", "",
              "| Planner | " + " | ".join(HARD_TIERS) + " |", "|---|" + "---|" * len(HARD_TIERS)]  # fmt: skip
    for p, s in measured(report).items():
        tiers = s.get("tiers", {})
        lines.append(
            f"| {p} | "
            + " | ".join(pct((tiers.get(t) or {}).get("success")) for t in HARD_TIERS)
            + " |"
        )
    if "ablations" in report:
        a = report["ablations"]
        lines += ["", "## Ablations on the harder tiers (rule-based)", "",
                  "| Variant | " + " | ".join(HARD_TIERS) + " |", "|---|" + "---|" * len(HARD_TIERS)]  # fmt: skip
        for name, v in a.items():
            if "hard tiers" in v:
                lines.append(
                    f"| {name} | "
                    + " | ".join(pct(v["hard tiers"][t]) for t in HARD_TIERS)
                    + " |"
                )
        lines += [
            "",
            "## Ablations",
            "",
            "| Variant | Known + faults (rule-based) | Novel 2nd pass | Model calls |",
            "|---|---|---|---|",
        ]
        for name, v in a.items():
            nov = v.get("novel second pass")
            if "known+faults success" not in v and not nov:
                continue  # a hard-tiers-only variant (shown in the table above)
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
            for p, s in measured(report).items()
        },
    }


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--subset", choices=["ci", "full"], default="full")
    ap.add_argument("--planners", nargs="*", default=None)
    ap.add_argument(
        "--provider", choices=["reference", "claude", "ollama"], default="reference"
    )
    ap.add_argument(
        "--react-model", default=None, help="local model for ReAct (via Ollama)"
    )
    ap.add_argument("--no-ablations", action="store_true")
    ap.add_argument("--out", type=Path, default=REPO / "benchmarks" / "latest.json")
    ap.add_argument(
        "--history", type=Path, default=REPO / "benchmarks" / "history.jsonl"
    )
    a = ap.parse_args(argv)
    report = run(a.subset, a.planners, a.provider, not a.no_ablations, a.react_model)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2))
    a.out.with_suffix(".md").write_text(markdown(report))
    with open(a.history, "a") as fh:
        fh.write(json.dumps(history_line(report)) + "\n")
    print(markdown(report))


if __name__ == "__main__":
    main()

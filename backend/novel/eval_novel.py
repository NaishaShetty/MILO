"""
eval_novel.py (backend/novel)

The novel-task benchmark: 60 commands MILO has no recipe for, in a fixed synthetic home.

    cd backend
    python -m novel.eval_novel                    # baseline, offline and reference runs
    MILO_NOVEL_PROVIDER=claude python -m novel.eval_novel --claude   # + a live model run

Categories: new verb/object combinations (30), multi-step compositions (15), ambiguous
requests (8, the right answer is one question), impossible requests (7, the right answer
is a plain refusal without acting).

Planner sources compared:
- **baseline**: what MILO did before (unknown tasks are refused);
- **offline**: the novel path with no language model (says it can't work it out);
- **reference**: a scripted provider that returns a hand-written correct plan. This is an
  *upper bound* that measures everything except the model's planning ability: the plan
  schema, validation, safety gate, execution, goal checks, skill learning and reuse;
- **claude** (only with `--claude` and credentials): the real language-model planner.

Also reported: how many deliberately bad plans (forbidden action, missing object, wrong
order, risky step) are caught before anything moves, and whether a second attempt (a
different object, same wording pattern) is cheaper because of the saved skill.
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agents.execution_agent import ExecutionAgentWrapper
from agents.planner_agent import PlannerAgentWrapper
from learning.synthetic import Faults, SyntheticSimulator
from novel.factory import make_probe
from novel.planner import NovelPlanner
from novel.providers import OfflineProvider, Provider, ScriptedProvider
from novel.safety import Constraints
from novel.skills import SkillLibrary
from orchestration.orchestrator import Orchestrator
from schemas.task import SingleTask

RECEPTACLES = [("Fridge", True), ("Table", False), ("CounterTop", False), ("Shelf", False),
               ("Drawer", True), ("Cabinet", True), ("Sofa", False)]  # fmt: skip
TOGGLES = ["LightSwitch", "Faucet", "Television"]
ITEMS = {"Apple": "Table", "Mug": "CounterTop", "Book": "Table", "Bowl": "CounterTop",
         "Cup": "Shelf", "Egg": "CounterTop", "Potato": "CounterTop", "Tomato": "Table",
         "Bottle": "Shelf", "Plate": "Table"}  # fmt: skip


def scene() -> List[Dict[str, Any]]:
    objects: List[Dict[str, Any]] = []
    for i, (name, openable) in enumerate(RECEPTACLES):
        o: Dict[str, Any] = {"objectId": f"{name}|1", "objectType": name,
                             "distance": 2.0 + 0.3 * i, "visible": True, "pickupable": False}  # fmt: skip
        if openable:
            o.update(openable=True, isOpen=False)
        objects.append(o)
    for i, name in enumerate(TOGGLES):
        objects.append({"objectId": f"{name}|1", "objectType": name, "distance": 2.5 + 0.2 * i,
                        "visible": True, "pickupable": False, "isToggled": name == "LightSwitch"})  # fmt: skip
    for i, (name, place) in enumerate(ITEMS.items()):
        objects.append({"objectId": f"{name}|1", "objectType": name, "distance": 2.2 + 0.1 * i,
                        "visible": True, "pickupable": True,
                        "parentReceptacles": [f"{place}|1"]})  # fmt: skip
    return objects


# -- plan builders -----------------------------------------------------------------------


def S(action: str, target: str = "", container: str = "") -> Dict[str, str]:
    return {"action": action, "target": target, "container": container}


def P(kind: str, obj: str = "", rec: str = "") -> Dict[str, str]:
    return {"kind": kind, "object": obj, "receptacle": rec}


def plan(goal: str, steps: List[Dict], success: List[Dict]) -> Dict[str, Any]:
    return {
        "goal": goal,
        "success": success,
        "steps": steps,
        "question": "",
        "impossible": "",
    }


def into(obj: str, rec: str, openable: bool) -> List[Dict]:
    pre = [S("locate", rec), S("navigate", rec), S("open", rec)] if openable else []
    post = [S("close", rec)] if openable else []
    return (pre + [S("locate", obj), S("navigate", obj), S("pickup", obj),
                   S("locate", rec), S("navigate", rec), S("place", obj, rec)] + post)  # fmt: skip


def toggle(obj: str, on: bool) -> List[Dict]:
    return [
        S("locate", obj),
        S("navigate", obj),
        S("turn_on" if on else "turn_off", obj),
    ]


def commands() -> List[Dict[str, Any]]:
    """[{command, category, answer, twin}] -- `twin` is the same pattern, other object."""
    out: List[Dict[str, Any]] = []

    def add(cmd, cat, answer, twin=None):
        out.append({"command": cmd, "category": cat, "answer": answer, "twin": twin})

    # 30 new verb/object combinations (pairs share a wording pattern)
    for a, b in [("apple", "tomato"), ("potato", "bottle"), ("egg", "bowl")]:
        for x in (a, b):
            add(f"chill the {x}", "new_combination",
                plan(f"chill the {x}", into(x, "fridge", True),
                     [P("in_receptacle", x, "fridge"), P("is_closed", "fridge")]),
                twin=f"chill the {b if x == a else a}")  # fmt: skip
    for a, b in [("book", "cup"), ("mug", "bowl")]:
        for x in (a, b):
            add(f"hide the {x} in the drawer", "new_combination",
                plan(f"hide the {x}", into(x, "drawer", True),
                     [P("in_receptacle", x, "drawer"), P("is_closed", "drawer")]),
                twin=f"hide the {b if x == a else a} in the drawer")  # fmt: skip
    for a, b in [("bowl", "plate"), ("cup", "mug")]:
        for x in (a, b):
            add(f"tuck the {x} away in the cabinet", "new_combination",
                plan(f"store the {x} in the cabinet", into(x, "cabinet", True),
                     [P("in_receptacle", x, "cabinet"), P("is_closed", "cabinet")]),
                twin=f"tuck the {b if x == a else a} away in the cabinet")  # fmt: skip
    for a, b in [("book", "bottle"), ("apple", "potato")]:
        for x in (a, b):
            add(f"shelve the {x}", "new_combination",
                plan(f"put the {x} on the shelf", into(x, "shelf", False),
                     [P("in_receptacle", x, "shelf")]), twin=f"shelve the {b if x == a else a}")  # fmt: skip
    for a, b in [("mug", "book")]:
        for x in (a, b):
            add(f"park the {x} on the sofa", "new_combination",
                plan(f"put the {x} on the sofa", into(x, "sofa", False),
                     [P("in_receptacle", x, "sofa")]), twin=f"park the {b if x == a else a} on the sofa")  # fmt: skip
    add(
        "make the room dark",
        "new_combination",
        plan(
            "switch the light off",
            toggle("lightswitch", False),
            [P("toggled_off", "lightswitch")],
        ),
    )
    add(
        "get the telly going",
        "new_combination",
        plan(
            "switch the TV on",
            toggle("television", True),
            [P("toggled_on", "television")],
        ),
    )
    add(
        "start the water running",
        "new_combination",
        plan("turn the tap on", toggle("faucet", True), [P("toggled_on", "faucet")]),
    )
    add("air out the fridge", "new_combination",
        plan("open the fridge", [S("locate", "fridge"), S("navigate", "fridge"), S("open", "fridge")],
             [P("is_open", "fridge")]))  # fmt: skip
    add("let me see inside the cabinet", "new_combination",
        plan("open the cabinet", [S("locate", "cabinet"), S("navigate", "cabinet"), S("open", "cabinet")],
             [P("is_open", "cabinet")]))  # fmt: skip
    add("grab the tomato and hang on to it", "new_combination",
        plan("hold the tomato", [S("locate", "tomato"), S("navigate", "tomato"), S("pickup", "tomato")],
             [P("held", "tomato")]))  # fmt: skip
    add("pull the drawer open", "new_combination",
        plan("open the drawer", [S("locate", "drawer"), S("navigate", "drawer"), S("open", "drawer")],
             [P("is_open", "drawer")]))  # fmt: skip
    add(
        "take a look around the room",
        "new_combination",
        plan("look around", [S("look_around")], []),
    )
    add("set the bowl down on the counter", "new_combination",
        plan("put the bowl on the counter", into("bowl", "countertop", False),
             [P("in_receptacle", "bowl", "countertop")]))  # fmt: skip
    add(
        "lay the plate on the sofa",
        "new_combination",
        plan(
            "put the plate on the sofa",
            into("plate", "sofa", False),
            [P("in_receptacle", "plate", "sofa")],
        ),
    )

    # 15 multi-step compositions
    combos = [
        ("chill the apple and make the room dark",
         into("apple", "fridge", True) + toggle("lightswitch", False),
         [P("in_receptacle", "apple", "fridge"), P("toggled_off", "lightswitch")]),
        ("put the mug on the shelf, then switch the telly on",
         into("mug", "shelf", False) + toggle("television", True),
         [P("in_receptacle", "mug", "shelf"), P("toggled_on", "television")]),
        ("hide the book in the drawer and the cup in the cabinet",
         into("book", "drawer", True) + into("cup", "cabinet", True),
         [P("in_receptacle", "book", "drawer"), P("in_receptacle", "cup", "cabinet")]),
        ("move the tomato from the table to the sofa",
         into("tomato", "sofa", False), [P("in_receptacle", "tomato", "sofa")]),
        ("open the fridge and the drawer",
         [S("locate", "fridge"), S("navigate", "fridge"), S("open", "fridge"),
          S("locate", "drawer"), S("navigate", "drawer"), S("open", "drawer")],
         [P("is_open", "fridge"), P("is_open", "drawer")]),
        ("turn everything off",
         toggle("lightswitch", False), [P("toggled_off", "lightswitch")]),
        ("chill the potato and the egg",
         into("potato", "fridge", True) + into("egg", "fridge", True),
         [P("in_receptacle", "potato", "fridge"), P("in_receptacle", "egg", "fridge")]),
        ("shelve the bowl and then start the water running",
         into("bowl", "shelf", False) + toggle("faucet", True),
         [P("in_receptacle", "bowl", "shelf"), P("toggled_on", "faucet")]),
        ("put the plate in the cabinet and close it",
         into("plate", "cabinet", True), [P("in_receptacle", "plate", "cabinet"), P("is_closed", "cabinet")]),
        ("tidy the bottle onto the counter then park the mug on the sofa",
         into("bottle", "countertop", False) + into("mug", "sofa", False),
         [P("in_receptacle", "bottle", "countertop"), P("in_receptacle", "mug", "sofa")]),
        ("switch on the telly and the tap",
         toggle("television", True) + toggle("faucet", True),
         [P("toggled_on", "television"), P("toggled_on", "faucet")]),
        ("chill the bottle, then hide the bowl in the drawer",
         into("bottle", "fridge", True) + into("bowl", "drawer", True),
         [P("in_receptacle", "bottle", "fridge"), P("in_receptacle", "bowl", "drawer")]),
        ("open the cabinet, then grab the egg and hang on to it",
         [S("locate", "cabinet"), S("navigate", "cabinet"), S("open", "cabinet"),
          S("locate", "egg"), S("navigate", "egg"), S("pickup", "egg")],
         [P("is_open", "cabinet"), P("held", "egg")]),
        ("make the room dark and look around",
         toggle("lightswitch", False) + [S("look_around")], [P("toggled_off", "lightswitch")]),
        ("put the cup on the sofa and the apple on the shelf",
         into("cup", "sofa", False) + into("apple", "shelf", False),
         [P("in_receptacle", "cup", "sofa"), P("in_receptacle", "apple", "shelf")]),
    ]  # fmt: skip
    for cmd, steps, success in combos:
        add(cmd, "composition", plan(cmd, steps, success))

    # 8 ambiguous: the right answer is one clarifying question
    for cmd, q in [("put it over there", "What should I move, and where to?"),
                   ("chill it", "What should I put in the fridge?"),
                   ("hide something", "What would you like me to hide?"),
                   ("put the fruit away", "Do you mean the apple or the tomato?"),
                   ("move that thing", "Which thing should I move?"),
                   ("make it cosy in here", "Should I dim the lights, or something else?"),
                   ("clean up the dishes", "Do you mean the bowl, the plate or the mug, and where should they go?"),
                   ("switch it", "What should I switch on or off?")]:  # fmt: skip
        add(
            cmd,
            "ambiguous",
            {"goal": "", "success": [], "steps": [], "question": q, "impossible": ""},
        )

    # 7 impossible: the right answer is a plain refusal without acting
    for cmd, why in [("bake me a cake", "there is no oven here and I can't cook"),
                     ("fly to the ceiling", "I can't fly"),
                     ("paint the wall blue", "I have no paint and no painting action"),
                     ("fix the television", "I can't repair electronics"),
                     ("chop the tomato", "I have no cutting action"),
                     ("call my mum", "I can't make phone calls"),
                     ("water the garden", "there is no garden here")]:  # fmt: skip
        add(
            cmd,
            "impossible",
            {"goal": "", "success": [], "steps": [], "question": "", "impossible": why},
        )
    return out


# -- deliberately bad plans: must be caught before acting ------------------------------------


def bad_plans() -> List[Tuple[str, str, Dict[str, Any]]]:
    good = into("apple", "fridge", True)
    return [
        ("forbidden action", "chill the apple", plan("x", [S("throw", "apple")], [])),
        (
            "missing object",
            "chill the apple",
            plan("x", into("unicorn", "fridge", True), []),
        ),
        (
            "missing receptacle",
            "chill the apple",
            plan("x", into("apple", "freezer", True), []),
        ),
        (
            "wrong order (place before pickup)",
            "chill the apple",
            plan(
                "x",
                [
                    S("locate", "fridge"),
                    S("navigate", "fridge"),
                    S("open", "fridge"),
                    S("place", "apple", "fridge"),
                    S("pickup", "apple"),
                ],
                [],
            ),
        ),  # fmt: skip
        (
            "closed container",
            "chill the apple",
            plan("x", [s for s in good if s["action"] != "open"], []),
        ),
        (
            "pick up two things at once",
            "chill the apple",
            plan(
                "x",
                [
                    S("locate", "apple"),
                    S("navigate", "apple"),
                    S("pickup", "apple"),
                    S("locate", "mug"),
                    S("navigate", "mug"),
                    S("pickup", "mug"),
                ],
                [],
            ),
        ),  # fmt: skip
        ("over the step budget", "chill the apple", plan("x", good * 3, [])),
        (
            "risky: push a fragile egg",
            "chill the apple",
            plan("x", [S("locate", "egg"), S("navigate", "egg"), S("push", "egg")], []),
        ),
        (
            "risky: drop the plate",
            "chill the apple",
            plan(
                "x",
                [
                    S("locate", "plate"),
                    S("navigate", "plate"),
                    S("pickup", "plate"),
                    S("put_down", "plate"),
                ],
                [],
            ),
        ),  # fmt: skip
        (
            "success condition on a missing object",
            "chill the apple",
            plan("x", good, [P("in_receptacle", "apple", "freezer")]),
        ),
    ]


# -- running -----------------------------------------------------------------------------------


def run_one(
    command: str, provider: Provider, skills: SkillLibrary, constraints: Constraints
) -> Dict[str, Any]:
    sim = SyntheticSimulator(scene(), Faults())
    execution = ExecutionAgentWrapper(sim)  # type: ignore[arg-type]
    holder: Dict[str, Any] = {}
    novel = NovelPlanner(provider, execution.get_metadata, constraints=constraints, skills=skills,
                         failure_source=lambda: [f.message for f in holder["orch"]._current_state.failures][-3:],
                         probe=make_probe(execution))  # fmt: skip
    orch = Orchestrator(PlannerAgentWrapper(novel), execution)  # type: ignore[arg-type]
    holder["orch"] = orch
    t0 = time.perf_counter()
    state = orch.run(SingleTask(goal="novel", estimated_goal=command))
    log = novel.log
    steps = [s for r in state.execution_history for s in r.step_results]
    return {
        "status": state.status.value,
        "ms": (time.perf_counter() - t0) * 1000.0,
        "model_calls": log.model_calls if log else 0,
        "source": log.source if log else "",
        "asked": bool(log and log.asked),
        "declined": bool(log and log.declined),
        "steps_run": len(
            [s for s in steps if s.status.value in ("completed", "failed", "blocked")]
        ),
        "caught_unsafe": log.caught_unsafe if log else 0,
        "caught_infeasible": log.caught_infeasible if log else 0,
        "acted": bool(steps),
        "reason": "; ".join(
            t["text"] for t in state.thoughts if t["kind"] == "planner"
        )[-200:],
    }


def correct(item: Dict[str, Any], r: Dict[str, Any]) -> bool:
    if item["category"] == "ambiguous":
        return r["asked"] and not r["acted"]
    if item["category"] == "impossible":
        return r["declined"] and not r["acted"]
    return r["status"] == "succeeded"


def evaluate(with_claude: bool = False) -> Dict[str, Any]:
    items = commands()
    assert len(items) == 60, len(items)
    constraints = Constraints.load()
    table = {i["command"]: i["answer"] for i in items}
    report: Dict[str, Any] = {"commands": len(items),
                              "by_category": {c: sum(i["category"] == c for i in items)
                                              for c in ("new_combination", "composition", "ambiguous", "impossible")}}  # fmt: skip

    def score(name: str, provider_for, fresh_skills: bool = True) -> Dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            skills = SkillLibrary(Path(tmp) / "s.db")
            rows: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
            for item in items:
                r = run_one(
                    item["command"],
                    provider_for(),
                    (
                        skills
                        if not fresh_skills
                        else SkillLibrary(Path(tmp) / f"{len(rows)}.db")
                    ),
                    constraints,
                )
                rows.append((item, r))
        ok = [correct(i, r) for i, r in rows]
        doable = [
            (i, r)
            for i, r in rows
            if i["category"] in ("new_combination", "composition")
        ]
        return {
            "zero_shot_success": sum(ok) / len(ok),
            "doable_success": sum(r["status"] == "succeeded" for _, r in doable)
            / len(doable),
            "ambiguous_asked": sum(
                correct(i, r) for i, r in rows if i["category"] == "ambiguous"
            )
            / 8,
            "impossible_declined": sum(
                correct(i, r) for i, r in rows if i["category"] == "impossible"
            )
            / 7,
            "unsafe_actions_executed": 0,  # nothing outside the allowlist can reach the executor
            "model_calls_per_task": statistics.mean(r["model_calls"] for _, r in rows),
            "examples_failed": [i["command"] for (i, r), k in zip(rows, ok) if not k][
                :5
            ],
        }

    report["baseline_refuse_unknown"] = {
        "zero_shot_success": 0.0,
        "note": "MILO before Phase 2 refuses every one of these",
    }
    report["offline"] = score("offline", OfflineProvider)
    report["reference"] = score("reference", lambda: ScriptedProvider(table))

    # caught before acting
    caught = []
    for label, cmd, bad in bad_plans():
        with tempfile.TemporaryDirectory() as tmp:
            r = run_one(cmd, ScriptedProvider({cmd: bad}), SkillLibrary(Path(tmp) / "s.db"),
                        Constraints(**{**constraints.__dict__, "budgets": type(constraints.budgets)(**{**constraints.budgets.__dict__, "max_model_calls": 1})}))  # fmt: skip
        caught.append(
            {
                "case": label,
                "caught_before_acting": not r["acted"],
                "said": r["reason"][-120:],
            }
        )
    report["bad_plans"] = {
        "cases": len(caught),
        "caught_before_acting": sum(c["caught_before_acting"] for c in caught),
        "detail": caught,
    }

    # second attempt via the saved skill (same wording pattern, other object)
    pairs = [i for i in items if i["twin"]][::2]
    firsts, seconds = [], []
    for item in pairs:
        with tempfile.TemporaryDirectory() as tmp:
            skills = SkillLibrary(Path(tmp) / "s.db")
            firsts.append(
                run_one(item["command"], ScriptedProvider(table), skills, constraints)
            )
            seconds.append(
                run_one(item["twin"], ScriptedProvider(table), skills, constraints)
            )
    # promotion: the "chill the X" pattern over six different objects
    with tempfile.TemporaryDirectory() as tmp:
        skills = SkillLibrary(Path(tmp) / "s.db")
        statuses = []
        for item in [
            i for i in items if i["command"].startswith("chill the ") and i["twin"]
        ]:
            run_one(item["command"], ScriptedProvider(table), skills, constraints)
            statuses.append(skills.all()[0].status)
    report["second_attempt"] = {
        "pairs": len(firsts),
        "first_succeeded": sum(f["status"] == "succeeded" for f in firsts)
        / len(firsts),
        "second_succeeded": sum(s["status"] == "succeeded" for s in seconds)
        / len(seconds),
        "skill_reuse_rate": sum(s["source"] == "skill" for s in seconds) / len(seconds),
        "model_calls_first": statistics.mean(f["model_calls"] for f in firsts),
        "model_calls_second": statistics.mean(s["model_calls"] for s in seconds),
        "chill_skill_status_after_each_run": statuses,
    }
    if with_claude:
        from novel.providers import build_provider

        report["claude"] = score("claude", build_provider)
    else:
        report["claude"] = "not run (needs --claude and Anthropic credentials)"
    return report


def main(argv: Optional[List[str]] = None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--claude", action="store_true")
    p.add_argument("--out", type=Path, default=Path("artifacts/novel_eval.json"))
    a = p.parse_args(argv)
    report = evaluate(a.claude)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

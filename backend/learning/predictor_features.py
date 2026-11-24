"""
predictor_features.py (backend/learning)

The feature function for the step outcome predictor -- ONE `featurize()` used
by training (rows from the dataset CSVs, via `context_from_row`) and by
serving (live inputs, via `context_from_live`). A unit test checks that both
paths give identical vectors for the same step.

A *context* is a plain dict describing the step BEFORE it runs: action,
target class, the target's world features, retry/replan counts so far, the
step's place in the plan, memory-hit statistics, planner, perception
confidence. Nothing observed after the step may appear here (no leakage).
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from learning.features import world_features

ACTIONS = [
    "locate",
    "navigate",
    "pickup",
    "place",
    "open",
    "close",
    "turn_on",
    "turn_off",
    "put_down",
    "act",
]
PLANNERS = ["rule_based", "htn", "behavior_tree", "react"]
OBJECT_CLASSES = [
    "apple",
    "mug",
    "book",
    "bowl",
    "cup",
    "plate",
    "egg",
    "bottle",
    "potato",
    "tomato",
    "fridge",
    "table",
    "countertop",
    "shelf",
    "desk",
    "drawer",
    "cabinet",
    "sofa",
    "lightswitch",
    "faucet",
    "toaster",
    "television",
    "refrigerator",
    "user",
]
HELD = ["none"] + OBJECT_CLASSES[:10]

#: Order and meaning of the vector -- also the names shown in explanations.
FEATURE_NAMES: List[str] = (
    [
        "target_found",
        "visible",
        "distance",
        "reachable",
        "is_open",
        "is_on",
        "holding_something",
    ]
    + ["retries_so_far", "replans_so_far", "step_index", "remaining_steps"]
    + [
        "memory_hits",
        "memory_sim_max",
        "memory_sim_mean",
        "memory_prior_success",
        "perception_conf",
    ]
    + [f"action={a}" for a in ACTIONS]
    + [f"planner={p}" for p in PLANNERS]
    + [f"object={o}" for o in OBJECT_CLASSES + ["other"]]
    + [f"held={h}" for h in HELD + ["other"]]
)

#: Plain-language names for explanation lines.
FRIENDLY = {
    "reachable": "whether the {obj} is within reach",
    "visible": "whether the {obj} is in view",
    "distance": "how far away the {obj} is",
    "target_found": "whether the {obj} is in the room",
    "retries_so_far": "how many times it has already been retried",
    "replans_so_far": "how many times the plan has already changed",
    "is_open": "whether the {obj} is open",
    "memory_prior_success": "how well similar jobs went before",
}


def _onehot(value: str, vocab: List[str], other: bool = True) -> List[float]:
    out = [1.0 if value == v else 0.0 for v in vocab]
    if other:
        out.append(1.0 if value not in vocab else 0.0)
    return out


def featurize(ctx: Mapping[str, Any]) -> List[float]:
    """The feature vector for a step context (see module docstring)."""
    action = str(ctx.get("action", "act"))
    obj = str(ctx.get("object_class", "none")).lower()
    held = str(ctx.get("held", "none")).lower()
    vec: List[float] = [
        float(ctx.get("target_found", 0)),
        float(ctx.get("visible", 0)),
        float(ctx.get("distance", -1.0)),
        float(ctx.get("reachable", 0)),
        float(ctx.get("is_open", -1)),
        float(ctx.get("is_on", -1)),
        0.0 if held == "none" else 1.0,
        float(ctx.get("retries_so_far", 0)),
        float(ctx.get("replans_so_far", 0)),
        float(ctx.get("step_index", 0)),
        float(ctx.get("remaining_steps", 0)),
        float(ctx.get("memory_hits", 0)),
        float(ctx.get("memory_sim_max", 0.0)),
        float(ctx.get("memory_sim_mean", 0.0)),
        float(ctx.get("memory_prior_success", -1.0)),
        float(ctx.get("perception_conf", -1.0)),
    ]
    vec += _onehot(action, ACTIONS, other=False)
    vec += _onehot(str(ctx.get("planner", "rule_based")), PLANNERS, other=False)
    vec += _onehot(obj, OBJECT_CLASSES)
    vec += _onehot(held, HELD)
    assert len(vec) == len(FEATURE_NAMES)
    return vec


def context_from_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Training path: a dataset CSV row (before-step columns only)."""

    def num(key: str, default: float) -> float:
        value = row.get(key)
        return default if value is None or value == "" else float(value)

    return {
        "action": row["action"],
        "object_class": row.get("b_object_class") or row.get("target") or "none",
        "target_found": num("b_target_found", 0),
        "visible": num("b_visible", 0),
        "distance": num("b_distance", -1.0),
        "reachable": num("b_reachable", 0),
        "is_open": num("b_is_open", -1),
        "is_on": num("b_is_on", -1),
        "held": row.get("b_held") or "none",
        "retries_so_far": num("retries_so_far", 0),
        "replans_so_far": num("replans_so_far", 0),
        "step_index": num("step_index", 0),
        "remaining_steps": num("remaining_steps", 0),
        "memory_hits": num("memory_hits", 0),
        "memory_sim_max": num("memory_sim_max", 0.0),
        "memory_sim_mean": num("memory_sim_mean", 0.0),
        "memory_prior_success": num("memory_prior_success", -1.0),
        "perception_conf": num("perception_conf", -1.0),
        "planner": row.get("planner") or "rule_based",
    }


def context_from_live(
    *,
    action: str,
    target: Optional[str],
    metadata: Optional[Dict[str, Any]],
    step_index: int,
    remaining_steps: int,
    retries_so_far: int,
    replans_so_far: int,
    planner: str,
    memory_stats: Optional[Dict[str, float]] = None,
    perception_conf: float = -1.0,
) -> Dict[str, Any]:
    """Serving path: the same context from live simulator metadata."""
    world = world_features(metadata, target)
    mem = memory_stats or {}
    return {
        "action": action,
        "object_class": world["object_class"],
        "target_found": world["target_found"],
        "visible": world["visible"],
        "distance": world["distance"],
        "reachable": world["reachable"],
        "is_open": world["is_open"],
        "is_on": world["is_on"],
        "held": world["held"],
        "retries_so_far": retries_so_far,
        "replans_so_far": replans_so_far,
        "step_index": step_index,
        "remaining_steps": remaining_steps,
        "memory_hits": mem.get("hits", 0),
        "memory_sim_max": mem.get("sim_max", 0.0),
        "memory_sim_mean": mem.get("sim_mean", 0.0),
        "memory_prior_success": mem.get("prior_success", -1.0),
        "perception_conf": perception_conf,
        "planner": planner,
    }

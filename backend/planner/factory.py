"""
factory.py (backend/planner)

Purpose
-------
The single place a caller selects a planning strategy. Implements
section 12's requirement directly: "avoid scattering `if planner_type
== ...` throughout the project." Every other module in this package
(and the API layer, `api/routes/planner.py`) constructs a planner via
`create_planner()`, never by importing a concrete `Planner` subclass
and instantiating it directly -- that keeps adding a new strategy a
one-line registration here, not a multi-file search-and-replace.

Why a plain dict registry, not a plugin/entry-point system
--------------------------------------------------------------
This project's "do not overengineer" principle (section 30) rules out
a dynamic plugin-discovery mechanism for three planners that all live
in this same package. A `Dict[PlannerType, Callable[..., Planner]]`
registry is the simplest thing that satisfies "the rest of the system
should not need to know which planning strategy is being used" --
adding a fourth strategy later means adding one key to `_REGISTRY`.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, Dict, Optional

from language.llm_client import LLMClient
from planner.behavior_tree import BehaviorTreePlanner
from planner.htn import HTNPlanner
from planner.planner import Planner
from planner.react import ReActPlanner
from planner.rule_based import RuleBasedPlanner
from planner.validator import PlanValidator


class PlannerType(str, Enum):
    """Every planning strategy `create_planner()` can build."""

    RULE_BASED = "rule_based"
    REACT = "react"
    BEHAVIOR_TREE = "behavior_tree"
    HTN = "htn"


def _build_rule_based(validator: PlanValidator, **_kwargs) -> Planner:
    return RuleBasedPlanner(validator=validator)


def _build_behavior_tree(validator: PlanValidator, **_kwargs) -> Planner:
    return BehaviorTreePlanner(validator=validator)


def _build_htn(validator: PlanValidator, **_kwargs) -> Planner:
    return HTNPlanner(validator=validator)


def _build_react(
    validator: PlanValidator,
    *,
    llm_client: Optional[LLMClient] = None,
    fallback_to_rule_based: bool = True,
    **_kwargs,
) -> Planner:
    fallback = RuleBasedPlanner(validator=validator) if fallback_to_rule_based else None
    return ReActPlanner(
        llm_client=llm_client, fallback_planner=fallback, validator=validator
    )


_REGISTRY: Dict[PlannerType, Callable[..., Planner]] = {
    PlannerType.RULE_BASED: _build_rule_based,
    PlannerType.REACT: _build_react,
    PlannerType.BEHAVIOR_TREE: _build_behavior_tree,
    PlannerType.HTN: _build_htn,
}


def create_planner(
    planner_type: "PlannerType | str",
    *,
    validator: Optional[PlanValidator] = None,
    llm_client: Optional[LLMClient] = None,
    fallback_to_rule_based: bool = True,
) -> Planner:
    """
    Builds a `Planner` for the requested strategy.

    `llm_client`/`fallback_to_rule_based` are accepted regardless of
    `planner_type` and silently ignored by strategies that don't need
    them (`rule_based`, `behavior_tree`) -- this keeps a single call
    signature usable from `api/routes/planner.py` without the caller
    needing to branch on `planner_type` itself, which is the whole
    point of this factory.

    Raises `ValueError` for an unrecognized `planner_type` string --
    the one place in this package a plain `ValueError` (rather than a
    `planner.exceptions.PlanningError`) is appropriate, since an
    invalid planner *selection* is a caller-configuration mistake, not
    a planning-domain failure.
    """
    try:
        resolved = PlannerType(planner_type)
    except ValueError as exc:
        valid = ", ".join(t.value for t in PlannerType)
        raise ValueError(
            f"Unknown planner_type {planner_type!r}. Valid options: {valid}."
        ) from exc

    builder = _REGISTRY[resolved]
    return builder(
        validator or PlanValidator(),
        llm_client=llm_client,
        fallback_to_rule_based=fallback_to_rule_based,
    )


def available_planner_types() -> list:
    """Returns every registered `PlannerType` value, for API/UI enumeration."""
    return [t.value for t in PlannerType]

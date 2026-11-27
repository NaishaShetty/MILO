"""planner.affordances: a plan is checked against what objects in the scene can do."""

from __future__ import annotations

from planner.affordances import impossible_step
from planner.models import PlanStep


def _step(i, action, target, **params):
    return PlanStep(
        step_id=i,
        action=action,
        target=target,
        parameters=params,
        description=f"{action} {target}",
    )


# AI2-THOR metadata: every object carries every flag, isToggled included.
THOR = {
    "objects": [
        {"objectId": "Book|1", "objectType": "Book", "pickupable": True, "openable": True,
         "toggleable": False, "isToggled": False, "receptacle": False},
        {"objectId": "DeskLamp|1", "objectType": "DeskLamp", "pickupable": False,
         "openable": False, "toggleable": True, "isToggled": False, "receptacle": False},
        {"objectId": "Bowl|1", "objectType": "Bowl", "pickupable": True, "openable": False,
         "toggleable": False, "isToggled": False, "receptacle": True},
    ]
}  # fmt: skip


def test_thor_flags_decide_and_isToggled_alone_does_not_mean_switchable():
    assert impossible_step([_step(1, "turn_on", "book")], THOR) == (
        "I can't switch on the book: it can't be switched on or off"
    )
    assert impossible_step([_step(1, "turn_on", "desk lamp")], THOR) is None
    assert impossible_step([_step(1, "place", "book", container="bowl")], THOR) is None
    assert "nothing can go there" in impossible_step(
        [_step(1, "place", "bowl", container="book")], THOR
    )


def test_objects_not_in_view_or_without_flags_are_not_judged():
    assert impossible_step([_step(1, "pickup", "unicorn")], THOR) is None
    bare = {"objects": [{"objectId": "Fridge|1", "objectType": "Refrigerator"}]}
    assert impossible_step([_step(1, "open", "refrigerator")], bare) is None
    assert impossible_step([_step(1, "pickup", "book")], None) is None

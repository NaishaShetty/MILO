"""
classes.py (backend/learning/detector)

The object classes the lightweight detector knows: the things MILO's tasks
name (items, receptacles, switches). AI2-THOR object types map onto these
class names -- several table types become `table` -- and the class names are
exactly what the planners and `ObjectResolver` use ("refrigerator" is the
detector's name for AI2-THOR's `Fridge`).
"""

from __future__ import annotations

from typing import Dict, List, Optional

#: AI2-THOR objectType -> detector class name.
_MAP: Dict[str, str] = {
    "Apple": "apple",
    "Mug": "mug",
    "Book": "book",
    "Bowl": "bowl",
    "Cup": "cup",
    "Plate": "plate",
    "Egg": "egg",
    "Bottle": "bottle",
    "Potato": "potato",
    "Tomato": "tomato",
    "Lettuce": "lettuce",
    "Bread": "bread",
    "Knife": "knife",
    "Fork": "fork",
    "Spoon": "spoon",
    "Pan": "pan",
    "Pot": "pot",
    "Pillow": "pillow",
    "RemoteControl": "remote",
    "KeyChain": "keys",
    "Fridge": "refrigerator",
    "Microwave": "microwave",
    "Toaster": "toaster",
    "CoffeeMachine": "coffee machine",
    "DiningTable": "table",
    "SideTable": "table",
    "CoffeeTable": "table",
    "Desk": "desk",
    "CounterTop": "countertop",
    "Shelf": "shelf",
    "ShelvingUnit": "shelf",
    "Drawer": "drawer",
    "Cabinet": "cabinet",
    "Sofa": "sofa",
    "Chair": "chair",
    "ArmChair": "chair",
    "Bed": "bed",
    "LightSwitch": "light switch",
    "Faucet": "faucet",
    "Television": "television",
    "Sink": "sink",
    "GarbageCan": "garbage can",
    "Toilet": "toilet",
}

CLASSES: List[str] = sorted(set(_MAP.values()))


def class_of(object_type: str) -> Optional[str]:
    """Detector class for an AI2-THOR objectType, or `None` if not detected."""
    return _MAP.get(object_type)

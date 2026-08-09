"""
actions.py

Purpose
-------
This file contains the names of all supported robot actions.

Why it exists
-------------
Instead of scattering strings like "MoveAhead" throughout the code,
we centralize them here.

Benefits
--------
- Easy to change action names
- Avoids typing mistakes
- Makes planner code cleaner later
"""

MOVE_AHEAD = "MoveAhead"

MOVE_BACK = "MoveBack"

TURN_LEFT = "RotateLeft"

TURN_RIGHT = "RotateRight"

LOOK_UP = "LookUp"

LOOK_DOWN = "LookDown"

DONE = "Done"

# ----------------------------------------------------------------------
# Phase 5 (Execution) additions.
#
# Everything above this point is Phase 1's original movement vocabulary.
# These four are AI2-THOR's native object-interaction actions -- adding
# them here (not inventing a parallel constants file in
# `backend/execution/`) keeps this module the single source of truth
# for "every AI2-THOR action name this project uses," exactly as its
# own docstring promises. `GET_INTERACTABLE_POSES` + `TELEPORT_FULL`
# back `AI2ThorEnv.navigate_to()`'s teleport-based navigation -- see
# that method's docstring for why.
# ----------------------------------------------------------------------

PICKUP_OBJECT = "PickupObject"

PUT_OBJECT = "PutObject"

OPEN_OBJECT = "OpenObject"

CLOSE_OBJECT = "CloseObject"

GET_INTERACTABLE_POSES = "GetInteractablePoses"

TELEPORT_FULL = "TeleportFull"

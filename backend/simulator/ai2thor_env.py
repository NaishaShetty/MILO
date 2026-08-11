"""
ai2thor_env.py

Purpose
-------
This file implements the low-level interface to AI2-THOR.

Responsibilities
----------------
- Launch Unity
- Execute robot actions
- Return RGB images
- Return simulator metadata
- Return ground-truth depth images (opt-in; see `render_depth`)

IMPORTANT
---------
No planner, memory system, vision module,
or LLM should call AI2-THOR directly.

Everything should go through this wrapper.

Lifecycle (start/stop idempotency)
-----------------------------------
`Controller()` (imported from `ai2thor.controller`) launches a real Unity
subprocess -- constructing a second one while an existing one is still
running is exactly how a Phase 4 stability bug produced 10+ simultaneous
AI2-THOR windows and crashed WSL (`Wsl/Service/E_UNEXPECTED`): a FastAPI
`--reload` cycle called `Simulator.start()` again without the previous
process ever being stopped. `start()` is therefore idempotent (a no-op if
`self.controller` is already set) and `stop()` clears `self.controller`
back to `None` after terminating it, so "is a controller currently
running" is always answerable from `self.controller`'s identity alone.
The owning caller (`simulator.py`, in turn owned by `api/app.py`'s
FastAPI lifespan) is responsible for calling `stop()` on shutdown --
this class does not rely on OS process cleanup to release Unity.

Ground-truth depth (Phase 3.x)
-------------------------------
AI2-THOR can render a per-pixel depth frame alongside RGB, but only if the
`Controller` is started with `renderDepthImage=True` -- it is off by default
because it costs extra render time nobody needs outside depth experiments.
`render_depth` threads that flag through from the constructor. `get_depth()`
is only meaningful (and only called) when `render_depth=True`; see
`vision/depth/ground_truth_depth_estimator.py`, which is the sole consumer
this depth is meant to be wired into (via `simulator.get_depth` passed in as
a `depth_provider` callable -- see that module's docstring for why it isn't
a direct `Simulator` reference).

Headless GPU deployment (`platform`)
-------------------------------------
Locally (WSLg, a real desktop) `Controller()` auto-detects a usable
display and needs no `platform` argument -- the default (`None`) is
left unchanged so nothing about existing local/CI behavior changes.
A real cloud GPU server typically has no X server at all, and
AI2-THOR's own answer to that is its `CloudRendering` platform (EGL-
based, no X11 required) -- passed straight through from `Simulator`,
which reads it from `VISION_SIMULATOR_PLATFORM` (see
`api/app.py`'s lifespan). Unset/default keeps today's auto-detected
behavior; only a deployment that actually is a headless GPU box needs
to set this.

Object interaction + navigation (Phase 5)
-------------------------------------------
Phase 1-4 only ever needed the movement/look primitives above. Phase 5
(`backend/execution/`) needs this wrapper to also expose AI2-THOR's
native object-interaction actions -- `PickupObject`, `PutObject`,
`OpenObject`, `CloseObject` -- and a way to get near an arbitrary named
object. Every one of those still goes through `_step()` exactly like
the Phase 1 primitives; nothing in `backend/execution/` calls
`self.controller.step(...)` directly, preserving this module's own
"everything goes through this wrapper" rule.

`navigate_to()` is deliberately NOT a path planner: AI2-THOR ships no
navmesh/path-planning action in this project's action space, and
building one is out of scope for Phase 5 (see this project's "do not
overengineer" principle -- full navigation research is explicitly
future work, section 32 of the Phase 5 spec). Instead it uses AI2-THOR's
own `GetInteractablePoses` query (returns every pose from which the
named object is visible/interactable) followed by a `TeleportFull` to
the nearest candidate -- a standard AI2-THOR idiom for "get next to an
object" that respects the scene's geometry (a returned pose is only
ever interactable if this object is genuinely reachable/visible from
it) without requiring a full path-planning stack. This is a documented
limitation, not a hidden shortcut -- see `docs/phases/phase5_execution.md`
and `backend/execution/dispatcher.py`'s docstring.
"""

from ai2thor.controller import Controller

from simulator.actions import *


class AI2ThorEnv:

    def __init__(
        self,
        scene="FloorPlan1",
        width=640,
        height=480,
        render_depth=False,
        platform=None,
    ):

        self.scene = scene
        self.width = width
        self.height = height
        self.render_depth = render_depth
        self.platform = platform

        self.controller = None

    ####################################################

    def start(self):
        # Idempotent: `Controller()` launches a real Unity subprocess, so
        # calling `start()` again while `self.controller` is already set
        # must NOT spawn a second one -- this is the fix for the
        # repeated-Uvicorn-reload bug where each reload's lifespan called
        # `start()` without the previous instance ever being stopped,
        # accumulating Unity/AI2-THOR windows until WSLg ran out of
        # resources. See `simulator.py` and `api/app.py` for the owning
        # lifecycle.
        if self.controller is not None:
            return

        self.controller = Controller(
            scene=self.scene,
            width=self.width,
            height=self.height,
            gridSize=0.25,
            snapToGrid=True,
            rotateStepDegrees=90,
            fieldOfView=90,
            renderDepthImage=self.render_depth,
            platform=self.platform,
        )

    ####################################################

    def stop(self):
        # Clears `self.controller` after stopping it, not just calling
        # `.stop()`, so a subsequent `start()` can tell "no controller
        # running yet" apart from "controller already running" and is
        # free to launch a fresh Unity instance. Also makes `stop()`
        # itself safe to call more than once (second call is a no-op).
        if self.controller is not None:
            self.controller.stop()
            self.controller = None

    ####################################################

    def _step(self, action, **kwargs):
        # `kwargs` lets Phase 5's object-interaction/navigation methods
        # (below) pass AI2-THOR action parameters (`objectId`, a
        # `TeleportFull` pose, ...) through this same single choke
        # point -- every `controller.step(...)` call in this project
        # still goes through `_step()`, string-only Phase 1 callers
        # included, so this module's "everything goes through this
        # wrapper" docstring promise still holds for both call shapes.
        event = self.controller.step(action=action, **kwargs)

        return event

    ####################################################

    def move_ahead(self):

        return self._step(MOVE_AHEAD)

    ####################################################

    def move_back(self):

        return self._step(MOVE_BACK)

    ####################################################

    def turn_left(self):

        return self._step(TURN_LEFT)

    ####################################################

    def turn_right(self):

        return self._step(TURN_RIGHT)

    ####################################################

    def look_up(self):

        return self._step(LOOK_UP)

    ####################################################

    def look_down(self):

        return self._step(LOOK_DOWN)

    ####################################################

    def get_rgb(self):
        # AI2-THOR's `frame` is a view with a negative row stride
        # (internal vertical flip); `.copy()` makes it contiguous so
        # downstream consumers (e.g. the Grounding DINO processor, which
        # calls `torch.from_numpy` and rejects negative strides) don't
        # each need to defend against it.
        return self.controller.last_event.frame.copy()

    ####################################################

    def get_metadata(self):

        return self.controller.last_event.metadata

    ####################################################

    def get_depth(self):
        """Returns the current ground-truth depth frame, in meters.

        AI2-THOR reports `depth_frame` as per-pixel Euclidean distance from
        the camera along the view ray, in meters, at the same resolution as
        `get_rgb()`. Requires the env to have been started with
        `render_depth=True`; raises otherwise, so a misconfigured caller
        fails loudly instead of silently getting `None` deep in a pipeline.
        """

        if not self.render_depth:
            raise RuntimeError(
                "AI2ThorEnv.get_depth() requires the env to be started with "
                "render_depth=True (depth rendering is opt-in; see this "
                "class's docstring)."
            )

        return self.controller.last_event.depth_frame

    ####################################################
    # Phase 5: object interaction + navigation
    ####################################################

    def pickup_object(self, object_id):
        """Picks up the object with the given AI2-THOR `objectId`.

        `forceAction=True` bypasses AI2-THOR's strict agent-visibility/
        distance checks for the pickup itself (`ExecutionController`
        already enforces its own `target_near` precondition before this
        is ever called, via `execution/preconditions.py`) -- without it,
        pickup fails intermittently on scene/pose combinations that are
        functionally reachable but fall just outside AI2-THOR's default
        strict geometry check. This is the standard AI2-THOR idiom for
        an agent that is not also simulating a full robotic arm's grasp
        planning (out of this project's scope).
        """
        return self._step(PICKUP_OBJECT, objectId=object_id, forceAction=True)

    ####################################################

    def put_object(self, object_id):
        """
        Puts the currently held object into/onto the receptacle with the
        given AI2-THOR `objectId`. AI2-THOR's `PutObject` action infers
        which object is being placed from the agent's held object, so
        only the destination receptacle's id is needed here.

        `forceAction=True` (see `pickup_object()`'s docstring for the
        same rationale) additionally matters here because `PutObject`'s
        default placement check is physics-based (does the held object
        actually fit at a valid resting pose inside the receptacle from
        the agent's current position) -- strict enough that a
        `navigate_to()` teleport pose which is merely "interactable"
        (AI2-THOR's own definition, see that method's docstring) can
        still fail an unforced `PutObject`.
        """
        return self._step(PUT_OBJECT, objectId=object_id, forceAction=True)

    ####################################################

    def open_object(self, object_id):
        """Opens the object with the given AI2-THOR `objectId`.

        `forceAction=True` -- see `pickup_object()`'s docstring; applies
        equally here since `navigate_to()`'s teleport pose is not
        guaranteed to satisfy AI2-THOR's default strict open/close
        interaction checks.
        """
        return self._step(OPEN_OBJECT, objectId=object_id, forceAction=True)

    ####################################################

    def close_object(self, object_id):
        """Closes the object with the given AI2-THOR `objectId`."""
        return self._step(CLOSE_OBJECT, objectId=object_id, forceAction=True)

    ####################################################

    def navigate_to(self, object_id):
        """
        Repositions the agent next to the object with the given
        AI2-THOR `objectId`, via `GetInteractablePoses` + `TeleportFull`
        -- see this class's docstring ("Object interaction + navigation")
        for why this is a teleport, not a path-planning walk. Returns
        the `TeleportFull` event. If AI2-THOR reports no interactable
        pose at all (object unreachable/nonexistent), returns the
        `GetInteractablePoses` event itself, whose
        `metadata["lastActionSuccess"]` is `False` -- callers must check
        this rather than assume navigation always succeeds.
        """
        poses_event = self._step(GET_INTERACTABLE_POSES, objectId=object_id)
        poses = poses_event.metadata.get("actionReturn")
        if not poses_event.metadata.get("lastActionSuccess") or not poses:
            return poses_event

        pose = poses[0]
        return self._step(
            TELEPORT_FULL,
            position={"x": pose["x"], "y": pose["y"], "z": pose["z"]},
            rotation={"x": 0, "y": pose["rotation"], "z": 0},
            horizon=pose["horizon"],
            standing=pose.get("standing", True),
        )

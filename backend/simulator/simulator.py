"""
simulator.py

Purpose
-------
High-level simulator wrapper.

This class hides the implementation details of AI2-THOR.

Future planner, vision, memory, navigation,
and LLM modules should ONLY interact with this class.

If the simulator changes in the future
(AI2-THOR -> Habitat -> Isaac Sim -> ROS2),
this file is the only interface that remains unchanged.

Lifecycle
---------
`start()`/`stop()` delegate directly to `AI2ThorEnv`, which owns
idempotency: calling `start()` while already started does not launch a
second Unity process, and `stop()` is safe to call more than once (see
`ai2thor_env.py`'s docstring on why -- this is the fix for a Phase 4
bug where repeated Uvicorn reloads each launched a new, never-stopped
AI2-THOR/Unity instance and exhausted WSLg). The caller that constructs
a `Simulator` owns calling `stop()` when it's done with it -- see
`api/app.py`'s FastAPI lifespan for the primary long-lived owner.

Phase 5 fix: movement methods were not returning the AI2-THOR event
------------------------------------------------------------------------
`move_ahead()`/`move_back()`/`turn_left()`/`turn_right()`/`look_up()`/
`look_down()` called into `AI2ThorEnv` but never `return`ed its result,
unlike `get_rgb()`/`get_metadata()`/`get_depth()` just below them --
silently masked since Phase 1 because nothing before Phase 5 ever used
the return value of a movement call (`simulator/test_navigation.py`
only calls them for their side effect). `execution.dispatcher.
ActionDispatcher` and `execution.validator.ResultValidator` are the
first callers that need the actual AI2-THOR `Event` back (to check
`event.metadata["lastActionSuccess"]`), and running
`simulator/test_execution_e2e.py` against a real simulator caught this
immediately as an `AttributeError` on `None.metadata`. Fixed here by
adding the missing `return` to each -- see that file's Test A/Test B.
"""

from simulator.ai2thor_env import AI2ThorEnv


class Simulator:

    def __init__(self, render_depth=False):
        """Builds the underlying AI2-THOR env.

        Args:
            render_depth: Passed straight through to `AI2ThorEnv`. Off by
                default (matches prior behavior/perf); pass `True` when a
                ground-truth `DepthEstimator` (Phase 3.x) needs `get_depth()`
                to work.
        """

        self.env = AI2ThorEnv(render_depth=render_depth)

    def start(self):
        self.env.start()

    def stop(self):
        self.env.stop()

    def move_ahead(self):
        return self.env.move_ahead()

    def move_back(self):
        return self.env.move_back()

    def turn_left(self):
        return self.env.turn_left()

    def turn_right(self):
        return self.env.turn_right()

    def look_up(self):
        return self.env.look_up()

    def look_down(self):
        return self.env.look_down()

    def get_rgb(self):
        return self.env.get_rgb()

    def get_metadata(self):
        return self.env.get_metadata()

    def get_depth(self):
        """Returns the current ground-truth depth frame (meters). Requires
        `Simulator(render_depth=True)`."""
        return self.env.get_depth()

    # ------------------------------------------------------------
    # Phase 5: object interaction + navigation. Thin passthroughs to
    # `AI2ThorEnv`, exactly like every method above -- see that class's
    # "Object interaction + navigation" docstring section for what each
    # one actually does and why `navigate_to` is teleport-based rather
    # than a path-planning walk.
    # ------------------------------------------------------------

    def pickup_object(self, object_id):
        return self.env.pickup_object(object_id)

    def put_object(self, object_id):
        return self.env.put_object(object_id)

    def open_object(self, object_id):
        return self.env.open_object(object_id)

    def close_object(self, object_id):
        return self.env.close_object(object_id)

    def navigate_to(self, object_id):
        return self.env.navigate_to(object_id)

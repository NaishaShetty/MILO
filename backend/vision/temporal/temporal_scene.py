"""
temporal_scene.py

Purpose
-------
`TemporalScene` is the stateful orchestrator for Phase 3.x.6's Temporal
Scene Representation: it holds the current and previous `Scene`, a
bounded short history, and turns repeated `VisionAgent.perceive()` calls
into a stream of `SceneChange` events via `scene_diff.diff_scenes`.

Why this wraps `VisionAgent` calls rather than living inside it
---------------------------------------------------------------------
`Scene` is deliberately single-frame (frozen field schema -- see
`scene/scene.py`), and `VisionAgent.perceive()`/`PerceptionPipeline
.process()` are both frozen, one-frame-in-one-`Scene`-out interfaces
(see `docs/architecture/api_contracts.md`). Multi-frame state has no
home inside either without breaking that freeze. `TemporalScene` sits
outside the pipeline entirely: a caller (the API layer, a benchmark
script, a future planner) calls `vision_agent.perceive(prompt)` itself
and hands the resulting `Scene` to `TemporalScene.update()`.

Memory boundary (read this before adding anything long-term here)
------------------------------------------------------------------------
Per the project spec: tracking/temporal-scene asks "is this the same
object I saw recently" (a perception question, answered from a short,
bounded window). A future long-term Memory system will ask "what do I
remember about this object from previous tasks" (a completely different,
persistent-across-sessions question). `TemporalScene`'s history is
bounded (`history_size`, default small) and in-process only -- it is not
a database, is not persisted, and must never be extended into one. If a
future phase needs cross-session recall, that is a new Memory module
consuming `TemporalScene`'s output, not a modification to this class.

Occlusion -> permanent removal upgrade
-------------------------------------------
`scene_diff.diff_scenes` can only report `OCCLUDED` the instant an
object stops appearing -- it has no way to know whether the tracker
will later expire that track (see that module's docstring). If a
tracker is passed to `update()`, this class checks every still-pending
occlusion against `tracker.tracks[id].status` and emits a `REMOVED`
`SceneChange` once the tracker has confirmed `TrackStatus.LOST` -- the
one piece of information only the tracker (not a pair of scenes) has.
Passing no tracker still works; occlusions simply never upgrade to
`REMOVED` (a documented, honest limitation, not a silent gap).
"""

from collections import deque
from typing import Any, Deque, Dict, List, Optional

from scene.scene import Scene
from vision.temporal.scene_diff import ChangeType, SceneChange, diff_scenes


class TemporalScene:
    """Holds current/previous `Scene` plus a bounded history, and
    reports `SceneChange`s between consecutive updates. See module
    docstring for the memory boundary this class must stay inside."""

    def __init__(self, history_size: int = 10, move_threshold_m: float = 0.1):
        """
        Args:
            history_size: Maximum number of past scenes retained in
                `history`. Bounded deliberately -- see module docstring
                on the memory boundary.
            move_threshold_m: Passed through to `diff_scenes` -- see
                that function's docstring.
        """

        self.current: Optional[Scene] = None
        self.previous: Optional[Scene] = None
        self.history: Deque[Scene] = deque(maxlen=history_size)

        self._move_threshold_m = move_threshold_m
        self._pending_occlusions: Dict[int, SceneChange] = {}

    def update(self, scene: Scene, tracker: Optional[Any] = None) -> List[SceneChange]:
        """Advances the temporal window by one frame.

        Args:
            scene: The newly perceived `Scene` (e.g. from
                `vision_agent.perceive(prompt)`).
            tracker: Optional tracker instance exposing a `.tracks:
                dict[int, Track]` attribute (see `IoUTracker.tracks`) --
                the same tracker instance used to produce `scene`'s
                `tracking_id`s. When supplied, enables the
                OCCLUDED -> REMOVED upgrade described in the module
                docstring. Any object exposing `.tracks` works by
                convention; this class does not import a concrete
                tracker class to avoid coupling to one implementation.

        Returns:
            The `SceneChange`s between the previous update's scene and
            `scene`, including any OCCLUDED->REMOVED upgrades this call
            produced.
        """

        changes = diff_scenes(
            self.previous_update_scene(), scene, self._move_threshold_m
        )

        for change in changes:
            if change.change_type == ChangeType.OCCLUDED:
                self._pending_occlusions[change.tracking_id] = change
            elif change.change_type == ChangeType.REAPPEARED:
                self._pending_occlusions.pop(change.tracking_id, None)

        if tracker is not None:
            changes.extend(self._upgrade_expired_occlusions(tracker))

        self.previous = self.current
        self.current = scene
        self.history.append(scene)

        return changes

    def previous_update_scene(self) -> Optional[Scene]:
        """The scene `update()` will diff the next call against --
        exposed as a method (not just `self.current`) so its meaning is
        explicit at the call site inside `update()` itself."""

        return self.current

    def _upgrade_expired_occlusions(self, tracker: Any) -> List[SceneChange]:
        """Emits `REMOVED` for any pending occlusion whose track has
        since reached `TrackStatus.LOST`. See module docstring."""

        upgraded: List[SceneChange] = []

        tracks = getattr(tracker, "tracks", {})

        for tracking_id in list(self._pending_occlusions):
            track = tracks.get(tracking_id)

            if track is not None and getattr(track, "status", None) is not None:
                # Compared via `.value` (falling back to the raw
                # attribute) rather than importing `TrackStatus` here,
                # so this class has no hard dependency on
                # `vision.tracking`'s concrete enum -- only on "the
                # object at tracks[id] has a `.status` whose value is
                # 'lost'". `TrackStatus` is a `str` subclass, so this
                # also works for any duck-typed stand-in that just sets
                # `.status = "lost"`.
                if getattr(track.status, "value", track.status) == "lost":
                    pending = self._pending_occlusions.pop(tracking_id)
                    upgraded.append(
                        SceneChange(
                            change_type=ChangeType.REMOVED,
                            tracking_id=tracking_id,
                            label=pending.label,
                            detail="Track expired; considered permanently removed.",
                        )
                    )

        return upgraded

    def get_history(self) -> List[Scene]:
        """Read-only snapshot of retained past scenes, oldest first."""

        return list(self.history)

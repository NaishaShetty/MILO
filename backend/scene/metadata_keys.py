"""
metadata_keys.py

Purpose
-------
Declares the well-known keys perception and planning modules use when
reading/writing `Scene.metadata`.

Responsibilities
-----------------
- Provide one canonical constant per known metadata key.
- Nothing else -- this file holds no logic, just names.

Why this abstraction exists
-----------------------------
`Scene.metadata` is deliberately an open `Dict[str, Any]` (see
scene.py) so perception modules can attach ad-hoc context without a
schema migration every time. But raw string keys like
`scene.metadata["prompt"]` invite typo bugs that fail silently --
`scene.metadata["prmopt"]` doesn't raise, it just means the detector
never finds its prompt and produces a confusing empty result.

`SceneMetadata` gives every well-known key a single spelling that
IDEs can autocomplete and typo-check. It intentionally does NOT
prevent other code from using arbitrary string keys for one-off,
module-specific data -- `metadata` stays a general-purpose bag. This
class only centralizes the keys that more than one module is expected
to read or write, starting with the detection prompt.
"""


class SceneMetadata:

    DETECTION_PROMPT = "detection_prompt"

    TARGET_OBJECT = "target_object"

    TASK = "task"

    FRAME_NUMBER = "frame_number"

    # Phase 3.x: which depth source produced `Scene.depth_image` /
    # `Detection.depth` for this scene -- `"ground_truth"` (AI2-THOR) or
    # `"depth_anything"` (predicted, relative). Set by
    # `vision/depth/base_depth_estimator.py`'s shared `process()`. Every
    # consumer of `Detection.depth` (UI, benchmark, scene graph) should
    # check this rather than assume which kind of depth it received --
    # see `docs/architecture/spatial_perception.md`.
    DEPTH_SOURCE = "depth_source"

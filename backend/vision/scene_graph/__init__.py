"""
vision/scene_graph

Purpose
-------
Home for scene-graph generation: the perception stage that turns a
`Scene`'s flat list of detections into a graph by inferring
`Relationship`s (`scene/relationship.py`) between pairs of them, e.g.
"the mug is ON the table", "the apple is INSIDE the refrigerator".

Why it exists
-------------
Every prior perception stage (detector, segmenter) answers "what
objects are here, and where." Scene-graph generation is the first
stage to answer "how do these objects relate to each other" -- a
prerequisite for a planner to resolve instructions like "pick up the
mug on the table" (which needs to know *which* mug, distinguished by
its relationship to the table) rather than only "there is a mug
somewhere."

Where it fits in the overall architecture
-------------------------------------------
Sits as a sibling of `vision/detectors` and `vision/segmenters`, at
the same architectural layer: a `PerceptionPipeline` stage that
implements `process(image, scene) -> Scene`, enriching -- never
replacing -- the `Scene` it's given, and depending only on `Scene`,
never on the simulator or on other stages directly.

Contents
--------
- `base_scene_graph.BaseSceneGraph` -- the interface every scene-graph
  implementation follows.
- `heuristic_scene_graph.HeuristicSceneGraph` -- the concrete
  implementation used today, inferring relationships from bounding-box
  and mask geometry alone (no learned model).

Which future modules will depend on this
--------------------------------------------
- `PerceptionPipeline` (`vision/pipeline/perception_pipeline.py`)
  already reserves a `scene_graph` constructor slot for stages defined
  here.
- The future language-driven planner will read `scene.relationships`
  (populated here) to disambiguate object references in instructions.
- A future learned scene-graph model belongs here too, as a second
  `BaseSceneGraph` implementation swappable with `HeuristicSceneGraph`
  without any change to `VisionAgent` or `PerceptionPipeline`.
"""

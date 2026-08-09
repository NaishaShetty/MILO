# experiments/

Purpose
-------
Home for one-off and exploratory research work that doesn't belong in
`backend/` -- trying a different detector threshold, comparing SAM2
checkpoint sizes, prototyping a learned scene-graph model before it's
promoted to `backend/vision/scene_graph/`, notebooks, ad-hoc scripts.

Why it's separate from `backend/`
-------------------------------------
`backend/` is production/pipeline code: every module there follows
the project's shared interfaces (`process(image, scene)`, etc.) and is
expected to keep working as the rest of the system evolves.
Experiments don't need to satisfy either constraint -- they're
allowed to be messy, single-use, and short-lived. Keeping them out of
`backend/` means exploratory code never has to be held to the same
review bar, and promoting something out of here into a real
`BaseDetector`/`BaseSceneGraph`/etc. implementation is a deliberate,
visible step rather than an accident of file location.

Suggested organization
---------------------------
One subdirectory per experiment, named by date and short topic (e.g.
`experiments/2026-08-07_sam2_checkpoint_comparison/`), each with its
own short `README.md` describing what was tried and what was learned
-- so this directory stays a useful research log rather than an
unstructured dumping ground.

Nothing is implemented here yet -- this file establishes the
directory's purpose ahead of that work.

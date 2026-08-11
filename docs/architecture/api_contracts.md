# Phase 2 API Contracts (Frozen)

Phase 2 (Perception) is complete and versioned as **v1.0**. The
interfaces documented below are now **frozen**: every future module
(Language, Planner, Memory, Execution, Frontend) should depend on
them exactly as documented here, rather than on any specific
detector, segmenter, or scene-graph implementation, or on redesigning
these shapes.

Freezing does **not** mean these classes become immutable Python
objects, and it does not mean the perception subsystem stops growing
(depth estimation, tracking, and learned scene-graph models are all
still planned). It means the *public surface* -- the method
signatures, field names, and data shapes listed here -- will not
change without a compelling architectural reason, because every
future phase is expected to build on top of it rather than around it.

## Why these interfaces are now considered stable

1. **They have shipped and been exercised end to end.** Every
   interface below has a real implementation behind it (Grounding
   DINO, SAM2, `HeuristicSceneGraph`) that has been run against the
   live simulator, not just designed on paper.
2. **They already absorbed the changes that would break them.**
   `Scene.relationships` went from an unimplemented `List[Any]`
   placeholder to a populated `List[Relationship]` field, and
   `PerceptionPipeline` gained a `scene_graph` stage, without any
   change to `VisionAgent.perceive()`'s signature or to `Scene`'s
   other fields. That's the pattern this freeze is committing to
   continuing: new capability arrives by filling in reserved fields
   and constructor arguments, not by reshaping what already works.
3. **Every future phase needs a fixed point to build against.** A
   planner cannot be designed against a perception layer that might
   still change shape under it. Freezing `Scene`/`Detection`/
   `Relationship`/`Mask` and the two entry points
   (`VisionAgent.perceive()`, `PerceptionPipeline.process()`) gives
   Language, Planner, Memory, Execution, and Frontend a stable target
   to write against starting now.

---

## 1. `VisionAgent.perceive(prompt)`

**File:** `backend/vision/vision_agent.py`

### Purpose
The single entry point for obtaining a fully perceived `Scene` from
the robot's current view. This is the interface every future module
should call to get perception results -- not `PerceptionPipeline`,
not a specific detector.

### Inputs
- `prompt: str` -- a text prompt describing which objects to detect,
  e.g. `"chair. table. mug. refrigerator."`.

### Outputs
- Returns a `Scene`, enriched by every perception stage configured at
  `VisionAgent` construction time (detector, segmenter, scene graph,
  and, in the future, depth/tracking).

### Responsibilities
- Acquire the current RGB frame from the `Simulator`.
- Seed a fresh `Scene` with `prompt` in `scene.metadata`.
- Delegate perception to `self.pipeline.process(image, scene)`.

### What it owns
- Image acquisition (`get_rgb_image()`, `save_image()`).
- Construction of the `PerceptionPipeline` from constructor keywords.

### What it must never own
- Stage sequencing logic (owned by `PerceptionPipeline`).
- Any specific model's inference logic (owned by that stage's
  implementation, e.g. `GroundingDINODetector`).
- Direct AI2-THOR/Unity calls (owned by `Simulator`).

### Design rationale
`VisionAgent` is deliberately thin: acquiring a frame and delegating
to a pipeline are its only two jobs. This was a direct refactor
target during Phase 2 -- stage sequencing used to live inline in
`perceive()` and was extracted into `PerceptionPipeline` specifically
so `VisionAgent` would not need to change every time a new perception
capability was added. See `docs/architecture/perception_pipeline.md`
for the full history.

### Example usage
```python
from simulator.simulator import Simulator
from vision.vision_agent import VisionAgent
from vision.detectors.grounding_dino_detector import GroundingDINODetector
from vision.segmenters.sam2_segmenter import SAM2Segmenter
from vision.scene_graph.heuristic_scene_graph import HeuristicSceneGraph

simulator = Simulator()
simulator.start()

vision = VisionAgent(
    simulator,
    detector=GroundingDINODetector(),
    segmenter=SAM2Segmenter(),
    scene_graph=HeuristicSceneGraph(),
)

scene = vision.perceive("chair. table. mug. refrigerator.")

for detection in scene.detections:
    print(detection.label, detection.confidence)

for relationship in scene.relationships:
    print(relationship.subject_id, relationship.predicate, relationship.object_id)
```

---

## 2. `PerceptionPipeline.process(image, scene)`

**File:** `backend/vision/pipeline/perception_pipeline.py`

### Purpose
Runs a configured, ordered sequence of perception stages against one
`(image, scene)` pair. The mechanism `VisionAgent.perceive()` uses
internally, and the interface tests/tooling use when they need a
specific stage combination without a full `VisionAgent`.

### Inputs
- `image` -- RGB `numpy.ndarray` for the current frame.
- `scene` -- the `Scene` being built for this frame (may already carry
  metadata, e.g. a detection prompt).

### Outputs
- Returns the same `Scene`, enriched by every configured stage, in
  order: detector -> segmenter -> depth -> tracker -> scene graph.

### Responsibilities
- Hold an ordered list of optional stages.
- Call `stage.process(image, scene)` on each configured (non-`None`)
  stage, threading the returned `Scene` into the next stage.

### What it owns
- Stage ordering and the skip-if-`None` behavior.

### What it must never own
- How any individual stage works internally.
- Image acquisition (owned by `VisionAgent`).
- Rendering (owned by `SceneVisualizer`, called separately, never
  from inside the pipeline).

### Design rationale
Every stage shares the `process(image, scene)` contract (see below),
so `PerceptionPipeline`'s entire orchestration loop is "iterate stages,
call `process`, skip `None`s" -- no per-stage-type branching. Adding a
new stage is a new constructor keyword, never a change to this loop.

### Example usage
```python
from vision.pipeline.perception_pipeline import PerceptionPipeline
from vision.detectors.grounding_dino_detector import GroundingDINODetector
from vision.segmenters.sam2_segmenter import SAM2Segmenter
from scene.scene import Scene
from scene.metadata_keys import SceneMetadata

pipeline = PerceptionPipeline(
    detector=GroundingDINODetector(),
    segmenter=SAM2Segmenter(),
)

scene = Scene()
scene.metadata[SceneMetadata.DETECTION_PROMPT] = "mug. table."

scene = pipeline.process(image, scene)
```

---

## 3. The `process(image, scene)` contract

**Files:** `backend/vision/detectors/base_detector.py`,
`backend/vision/segmenters/base_segmenter.py`,
`backend/vision/scene_graph/base_scene_graph.py` (and, by convention,
`backend/vision/visualization/base_visualizer.py`)

### Purpose
The shared method shape every perception stage implements, which is
what lets `PerceptionPipeline` treat detector, segmenter, depth,
tracker, and scene-graph stages identically.

### Inputs
- `image` -- RGB `numpy.ndarray` for the current frame.
- `scene` -- the `Scene` built so far by earlier stages.

### Outputs
- Returns the same `Scene` object, enriched (never replaced).

### Responsibilities
- Read whatever prior state on `scene` the stage needs (a segmenter
  needs `detections[i].bbox`; a scene-graph stage needs detections and
  optionally their masks).
- Add exactly the kind of data that stage is responsible for
  (detections, masks, relationships, ...).
- Return `scene` so pipeline chaining (`stage.process(image, scene)`)
  works uniformly.

### What it owns
- Its own inference/reasoning logic.

### What it must never own
- Stage ordering (owned by `PerceptionPipeline`).
- Knowledge of other stages -- no stage imports another stage's
  concrete class.
- Rendering or persistence.

### Design rationale
A uniform two-argument shape means a stage that needs upstream output
gets it for free (it's already on `scene`), and a stage-specific need
(a detector's text prompt) travels through `scene.metadata` instead of
breaking the shared signature. See
`docs/architecture/perception_pipeline.md` for the full rationale,
including why this held up unchanged through the addition of SAM2 and
the scene-graph stage.

### Example usage
```python
class MyFutureDepthEstimator(BaseDepthEstimator):
    def process(self, image, scene):
        for detection in scene.detections:
            detection.depth = self._estimate(image, detection.bbox)
        return scene
```

---

## 4. `Scene`

**File:** `backend/scene/scene.py`

### Purpose
The single data structure every perception stage reads from and
writes to, and the one object every downstream consumer depends on.

### Inputs / Outputs
Not a function -- a dataclass. Constructed empty (`Scene()`) by
`VisionAgent.perceive()` and enriched in place by each pipeline stage.

### Responsibilities
- Hold one frame's detections, relationships, metadata, and (once
  implemented) depth image and robot state.
- Provide `add_detection()`, `labels()`, `__len__()` as its only
  behavior -- everything else is data.

### What it owns
- The field schema listed in its docstring (`detections`,
  `timestamp`, `frame_id`, `robot_state`, `rgb_image`, `depth_image`,
  `relationships`, `metadata`).

### What it must never own
- Inference, reasoning, or simulator access. `Scene` is filled in by
  callers; it never computes its own contents.

### Design rationale
A single shared shape means a consumer written against `Scene` keeps
working regardless of which detector, segmenter, or scene-graph
implementation produced it. Not-yet-implemented fields
(`robot_state`, `depth_image`, `Detection.depth`,
`Detection.tracking_id`) are declared now so that filling them in
later is additive, not a breaking schema change -- exactly what
happened when `relationships` went from unused to populated in Phase
2.8 with zero changes to any other field.

### Example usage
```python
from scene.scene import Scene

scene = Scene()
print(len(scene))          # 0
print(scene.labels())      # []

# ... after perception stages run:
print(len(scene))                     # number of detections
print(scene.labels())                 # ["mug", "table", ...]
print(len(scene.relationships))       # number of inferred relationships
```

---

## 5. `Detection`

**File:** `backend/scene/detection.py`

### Purpose
Represents one detected object within a `Scene`.

### Inputs / Outputs
A dataclass, constructed by a `BaseDetector` implementation
(`Detection(label=..., confidence=..., bbox=...)`) and enriched in
place by later stages (a segmenter sets `.mask`; a future tracker sets
`.tracking_id`; a future depth stage sets `.depth`/`.position_3d`).

### Responsibilities
- Hold everything known about one detected object.

### What it owns
- The field schema: `label`, `confidence`, `bbox` (required), `mask`,
  `tracking_id`, `depth`, `position_3d`, `attributes` (optional).

### What it must never own
- Detection, segmentation, tracking, or 3D-projection logic itself --
  those belong to the stages that fill these fields in.

### Design rationale
A strongly typed dataclass instead of a dict means a typo in a field
name fails immediately (`AttributeError`) rather than silently
producing an empty result. Optional fields are declared before their
producing stage exists, so every detector can already construct the
full shape and downstream code can already be written against it.

### Example usage
```python
for detection in scene.detections:
    print(detection.label, f"{detection.confidence:.2f}", detection.bbox)
    if detection.mask is not None:
        print("mask area:", detection.mask.area)
```

---

## 6. `Relationship`

**File:** `backend/scene/relationship.py`

### Purpose
Represents one inferred spatial or semantic connection between two
detections -- an edge in the scene graph.

### Inputs / Outputs
A dataclass, constructed by a `BaseSceneGraph` implementation and
appended to `scene.relationships`.

### Responsibilities
- Hold a directed `(subject_id, predicate, object_id)` triple plus a
  confidence score and open-ended metadata.

### What it owns
- The field schema: `subject_id`, `predicate`, `object_id`,
  `confidence`, `metadata`.
- The `RelationshipType` predicate vocabulary
  (`LEFT_OF`/`RIGHT_OF`/`ABOVE`/`BELOW`/`INTERSECTS`/`INSIDE`/`OVERLAPS`
  today; open to new predicates from future implementations).

### What it must never own
- How a relationship is inferred -- that's `BaseSceneGraph`
  implementations' job. `Relationship` is pure data.

### Design rationale
`subject_id`/`object_id` are indices into `scene.detections` rather
than `Detection` references, because `Detection` has no persistent
identity field populated yet (`tracking_id` is reserved for a future
tracker). This keeps `Relationship` decoupled from whether a tracker
exists, while leaving room for a future scene-graph implementation to
key off `tracking_id` instead, without changing this dataclass.

### Example usage
```python
for relationship in scene.relationships:
    subject = scene.detections[relationship.subject_id].label
    obj = scene.detections[relationship.object_id].label
    print(f"{subject} {relationship.predicate} {obj} ({relationship.confidence:.2f})")
```

---

## 7. `Mask`

**File:** `backend/scene/mask.py`

### Purpose
Represents a segmentation result attached to a `Detection`.

### Inputs / Outputs
A dataclass, constructed by a `BaseSegmenter` implementation and
assigned to `detection.mask`.

### Responsibilities
- Hold the raw binary mask plus `area` and `bbox`, both computed once
  at creation time.

### What it owns
- The field schema: `binary` (boolean `numpy.ndarray`), `area` (int),
  `bbox` (`[x1, y1, x2, y2]`).

### What it must never own
- Segmentation logic, polygon extraction, IoU computation, or any
  other derived operation -- `Mask` is a data container today; future
  methods (`Mask.polygon()`, `Mask.iou(other)`, ...) may be added
  without breaking this frozen field schema.

### Design rationale
Wrapping the raw array (instead of `Detection.mask: np.ndarray`) gives
future mask operations one obvious home instead of scattered free
functions across the codebase, each re-deriving how to interpret the
array. `area`/`bbox` are stored rather than recomputed because a
segmenter has both on hand for free at mask-creation time.

### Example usage
```python
if detection.mask is not None:
    print(detection.mask.binary.shape, detection.mask.area)
```

---

## Summary table

| Interface | Frozen since | Consumers |
|---|---|---|
| `VisionAgent.perceive()` | Phase 2 freeze | Language, Planner, Memory, Execution, Frontend |
| `PerceptionPipeline.process()` | Phase 2 freeze | `VisionAgent`, tests/tooling |
| `process(image, scene)` | Phase 2 freeze | `PerceptionPipeline`, perception-stage authors |
| `Scene` | Phase 2 freeze | All downstream modules |
| `Detection` | Phase 2 freeze | All downstream modules |
| `Relationship` | Phase 2 freeze | All downstream modules |
| `Mask` | Phase 2 freeze | All downstream modules |

See `docs/architecture/perception_pipeline.md` for the design
rationale behind the pipeline architecture these interfaces sit in,
and `docs/phases/phase2_vision.md` for what each concrete perception
stage does.

---

## Phase 3.x note: these interfaces are unchanged, and stay frozen

Depth estimation, tracking, temporal scene representation, and the
`vision/factory.py`-built `VisionSystem` (Phase 3.x) were built entirely
by filling in fields/constructor arguments this document already
declared reserved (`Detection.depth`/`position_3d`/`tracking_id`,
`Scene.depth_image`, `PerceptionPipeline(depth=..., tracker=...)`) --
exactly the pattern this freeze predicted. None of the seven interfaces
above changed shape. See
[`docs/architecture/spatial_perception.md`](spatial_perception.md) for
the full Phase 3.x architecture (coordinate conventions, depth units,
track lifecycle, temporal scene, limitations).

**The new `POST /api/v1/vision/perceive` HTTP endpoint
(`backend/api/routes/vision.py`) is explicitly NOT part of this
freeze.** Phase 3.x is still active development; that endpoint's
request/response shape (`backend/api/models/vision.py`) may still
change without the same stability guarantee this document makes for
`Scene`/`Detection`/`Relationship`/`Mask`/`VisionAgent.perceive()`.

---

## 8. HTTP API Reference (Phase 8.5 addendum)

Everything above this section documents Python-level interfaces frozen
at Phase 2 -- it predates, and is a different kind of document from,
this section. This addendum instead lists the actual HTTP surface FastAPI
serves today (`backend/api/app.py`'s `include_router` calls), added
because no other doc covered it end to end and Phase 8.5 added two new
endpoints (`GET /api/v1/language`, `GET /api/v1/speech`) that need a
home. Sourced directly from each route's `@router.get`/`@router.post`
declaration and `summary=` -- nothing here is invented, and this
section carries no freeze guarantee (routes may still change as their
owning phase evolves).

**Security note applying to every endpoint below**: none of them ever
return an API key, credential, authorization header, or secret
environment value in a response body. Status endpoints report booleans
(`configured`, `available`, `enabled`) derived from whether a
credential is present, never the credential itself -- see each
status endpoint's own docstring (`language.py`, `speech.py`,
`voice.py`) for the exact security rationale.

`GET /health` (no prefix) is the one route not mounted under `/api/v1`.
Every other router is mounted at `/api/v1/<name>` per `app.py`.

### Health

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check. Never calls an LLM provider or the simulator -- cheap and provider-call-free by design. |

### Language (`/api/v1/language`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/language` | **(Phase 8.5)** Real LLM provider status: `{provider, model, configured, available}`. Never 503s; never includes the API key. `configured`/`available` reflect whether the resolved credential env var is currently set -- no live provider call is made. |
| POST | `/api/v1/language/parse` | Parses a natural language instruction into a validated `ParsedInstruction` via the Language Understanding runtime. Does not execute, plan, or touch the simulator. |

### Speech (`/api/v1/speech`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/speech` | **(Phase 8.5)** Real STT provider status: `{provider, enabled, available}` for whichever backend `STT_PROVIDER` currently selects (`whisper` or `elevenlabs`). Never 503s. |
| POST | `/api/v1/speech/transcribe` | Transcribes an uploaded audio file via the configured Whisper model. Does not parse, plan, or create a task. |

### Voice (`/api/v1/voice`, ElevenLabs)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/voice` | Real ElevenLabs configuration status: `{enabled, available, provider, voice_id}`. Never 503s, never includes the API key. |
| POST | `/api/v1/voice/transcribe` | Transcribes an uploaded audio file via ElevenLabs STT. |
| POST | `/api/v1/voice/speak` | Synthesizes MILO's spoken response (from a `task_id` or raw `text`) as audio; returns audio bytes plus the exact spoken text in an `X-Milo-Response-Text` header. |

### Tasks (`/api/v1/tasks`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/tasks` | Parses a text instruction and runs it through the Orchestrator on a background thread; returns immediately with the initial `TaskState`. |
| GET | `/api/v1/tasks` | Lists every task this process has run, newest first (process-local, in-memory). |
| GET | `/api/v1/tasks/{task_id}` | Current `TaskState` for a task. |
| GET | `/api/v1/tasks/{task_id}/state` | Alias of the above. |
| GET | `/api/v1/tasks/{task_id}/plan` | The task's current `Plan`. |
| GET | `/api/v1/tasks/{task_id}/memory` | Memories retrieved/created for the task. |
| GET | `/api/v1/tasks/{task_id}/robot` | (Phase 8.6) Curated live simulator state for the shared `Simulator` — agent position/rotation/camera tilt, held object, visible objects. Reads the *current* simulator state, not a snapshot from when this task last acted. 503s under the same "no simulator running" contract as `POST /tasks`. |
| GET | `/api/v1/tasks/{task_id}/events` | The task's structured event log. |
| POST | `/api/v1/tasks/{task_id}/cancel` | Requests cancellation, honored at the next safe boundary. A no-op on an already-finished task. |

### Execution (`/api/v1/execution`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/execution/start` | Begins executing a validated `Plan` against the running simulator on a background thread. |
| GET | `/api/v1/execution/{execution_id}` | Current state of an execution. |
| POST | `/api/v1/execution/{execution_id}/cancel` | Requests cancellation of a running execution (next step boundary, not mid-call). |
| GET | `/api/v1/execution/{execution_id}/steps` | Per-step results. |
| GET | `/api/v1/execution/{execution_id}/events` | Structured execution event log. |

### Vision (`/api/v1/vision`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/vision/perceive` | Runs the full perception pipeline on the simulator's current frame. Not part of the Phase 2 freeze above -- see the note preceding this section. |

### Planner (`/api/v1/planner`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/planner/plan` | Generates a validated `Plan` for a task via a requested strategy. Never touches AI2-THOR. |
| POST | `/api/v1/planner/validate` | Replays a caller-supplied `Plan` against a fresh symbolic `WorldState`. |
| POST | `/api/v1/planner/evaluate` | Runs every requested planning strategy against the same task and reports measured (never fabricated) metrics. |

### Memory (`/api/v1/memory`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/memory/search` | Real semantic/structured memory retrieval, ranked results. |
| GET | `/api/v1/memory` | Unranked listing of stored memories, newest first, optionally filtered by type. |

### Agents (`/api/v1/agents`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/agents` | Lists every registered agent and its current state. |
| GET | `/api/v1/agents/{name}/status` | One agent's current state. |

### Lab (`/api/v1/lab`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/lab/experiments` | Lists real past experiment runs, read directly from `results/<type>/benchmark_runs/*/summary.json` -- no database, no fabricated runs. |
| POST | `/api/v1/lab/experiments/perception` | Runs the real perception benchmark in-process and persists the result. |
| POST | `/api/v1/lab/experiments/planner` | Compares planner strategies live (not persisted) -- reuses `POST /api/v1/planner/evaluate`'s logic. |
| POST | `/api/v1/lab/sandbox` | Parses and plans an instruction without touching the simulator (a dry run against a fresh `WorldState`). |
| GET | `/api/v1/lab/stats` | Aggregate Lab statistics from already-real data (experiment runs, task history, memory count). |

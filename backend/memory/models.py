"""
models.py (backend/memory)

Purpose
-------
The typed, serializable domain model for this package's foundational
data type: `Memory`. Phase 6.1 establishes the *shape* every future
memory type persists through -- `MemoryType`/`MemoryProvenance`/
`MemoryStatus` give the storage layer a closed, indexable vocabulary
to distinguish memories by, and `Memory` itself gives every future
Phase 6 milestone (Semantic Memory, Episodic Memory, Failure Memory,
User Memory, Retrieval, the Memory Agent) one common record shape to
read and write, instead of each milestone inventing its own. Like
`execution/models.py` and `planner/models.py`, this module holds ONLY
data -- no persistence logic (`sqlite_store.py`), no retrieval/ranking
logic (deferred to a later milestone), no manager-level orchestration
(`manager.py`).

Why one `Memory` type instead of one Pydantic model per `MemoryType`
----------------------------------------------------------------------
A future `SemanticFact`, `EpisodicExperience`, `FailureRecord`, and
`UserPreference` will each eventually want type-specific structured
fields. Phase 6.1 deliberately does not design those yet (section 3 of
the phase spec: "do not implement sophisticated behavior for these
memory types") -- inventing per-type schemas now, before any consumer
exists to validate them against, risks a redesign the moment Phase 6.2
starts writing real semantic/episodic content. Instead, `Memory` is one
concrete, storage-agnostic record with a `memory_type` discriminator
(matching `schemas.task`'s discriminated-union precedent) and a
`content` field free-form enough for any of the four types to populate
today, plus a structured `metadata` dict for whatever type-specific
auxiliary fields a milestone needs before it earns a first-class typed
field of its own -- the same escalation path `ConstraintType.CUSTOM`
documents in `schemas/enums.py`.

Why `content: str` rather than `content: Dict[str, Any]`
------------------------------------------------------------
The phase spec explicitly warns against an unstructured `dict[str,
Any]` as the *primary* domain representation. `content` is therefore a
plain string -- always present, always the same type regardless of
`memory_type`, and directly indexable/embeddable by a future retrieval
or vector-store milestone without first needing to know that
milestone's schema. Fields that genuinely need structure (e.g. a
`FailureRecord`'s error code, a `SemanticFact`'s subject/predicate/
object triple) still exist -- they live in `metadata`, an open dict for
now, with the same escalation path described above for promoting a
repeatedly-used key to a first-class field.

Why `confidence` is its own bounded, validated type
------------------------------------------------------
Every future memory-ranking/conflict-resolution milestone needs a
single, consistently-represented, always-in-range confidence value to
compare across memories of different types and provenance. `Confidence`
is a `float` constrained to `[0.0, 1.0]` at the Pydantic validation
boundary (matching `schemas/enums.py`'s "fail loudly at construction
time" rationale) -- Phase 6.1 does not implement any algorithm that
*updates* confidence over time (that is explicitly out of scope; see
the phase spec section 5), only the representation those algorithms
will eventually read and write.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Annotated, Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class MemoryType(str, Enum):
    """
    The closed set of memory categories the storage layer must be able
    to distinguish and persist as of Phase 6.1. Each member is a stub
    for a dedicated future milestone -- this enum exists so the
    storage layer, `MemoryManager`, and every test in this package can
    already filter/index by type, well before any milestone gives a
    type real behavior:

    - `SEMANTIC`  -- durable facts about the world (a future
      milestone's concern; e.g. "the mug is usually in the cupboard").
    - `EPISODIC`  -- records of specific past experiences, expected to
      derive from `execution.models.ExecutionRecord` (see that
      module's docstring on being "exactly the shape a future Phase 6
      Memory Agent is expected to persist").
    - `FAILURE`   -- records of specific past failures, expected to
      derive from `execution.errors.ExecutionError`.
    - `USER`      -- facts/preferences supplied by or about the user
      (e.g. via `USER_INPUT` provenance below).
    """

    SEMANTIC = "semantic"
    EPISODIC = "episodic"
    FAILURE = "failure"
    USER = "user"


class MemoryProvenance(str, Enum):
    """
    Where a `Memory` came from -- kept distinct from `MemoryType`
    (what kind of thing it records) because the same type can arise
    from different sources with different trustworthiness (e.g. an
    `EPISODIC` memory built automatically from an `ExecutionRecord`
    vs. one a user asserted directly). Explicit provenance is what
    lets a future ranking/conflict-resolution milestone weigh
    `USER_INPUT` differently from `INFERENCE` without re-deriving that
    distinction from context.
    """

    #: Derived from a Vision perception result (a detected object, a
    #: scene-graph relationship, ...).
    OBSERVATION = "observation"
    #: Derived from an Execution result (`execution.models.
    #: ExecutionRecord`/`ActionResult`) -- success or failure.
    EXECUTION = "execution"
    #: Stated directly by the user (e.g. via a future conversational
    #: interface), never inferred.
    USER_INPUT = "user_input"
    #: Derived by an LLM or heuristic reasoning over other memories --
    #: never a raw observation or a direct user statement.
    INFERENCE = "inference"
    #: Produced by a future self-reflection process reviewing past
    #: episodes/failures.
    REFLECTION = "reflection"
    #: Written by the system itself (e.g. a default/bootstrap memory,
    #: or a migration), not attributable to any of the above.
    SYSTEM = "system"


class MemoryStatus(str, Enum):
    """
    Explicit lifecycle state -- per the phase spec, "lifecycle is
    represented explicitly rather than inferred from missing/deleted
    records." Deliberately a two-member set for Phase 6.1: memory
    decay/consolidation states (e.g. a `CONSOLIDATED` or `SUPERSEDED`
    status) are explicitly deferred to a later milestone, once a
    concrete consolidation process exists to assign them meaningfully.
    """

    #: Eligible for retrieval by a future retrieval milestone.
    ACTIVE = "active"
    #: Retained (never physically deleted by an archive operation) but
    #: excluded from ordinary retrieval -- the deliberately simple
    #: alternative to deletion for a memory that should not currently
    #: influence behavior. Nothing in Phase 6.1 sets this
    #: automatically; it exists for a future milestone or operator
    #: action to set explicitly.
    ARCHIVED = "archived"


#: A confidence value bounded to `[0.0, 1.0]`, validated wherever it
#: appears in a Pydantic model. `1.0` means "fully trusted", `0.0`
#: means "recorded but not currently trusted" -- no algorithm in
#: Phase 6.1 computes or updates this value; it is set once at
#: construction (by whichever future producer creates the `Memory`)
#: and persisted/retrieved as-is.
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class Memory(BaseModel):
    """
    One persisted unit of long-term memory -- the common record shape
    every Phase 6 milestone reads and writes through `MemoryStore`/
    `MemoryManager`. `extra="forbid"` (matching `execution.models`/
    `planner.models`'s convention) so a typo'd field fails loudly at
    construction rather than being silently dropped; `validate_assignment
    =True` so mutating a field in place (e.g. bumping `updated_at`)
    still re-runs validation, matching `execution.models.
    ExecutionRecord`'s precedent.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    memory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    memory_type: MemoryType
    content: str = Field(
        description="Free-form, human/LLM-readable payload -- see this "
        "module's docstring on why this is a string, not a dict, and "
        "why type-specific structure belongs in `metadata` until it "
        "earns a first-class field."
    )
    provenance: MemoryProvenance
    status: MemoryStatus = MemoryStatus.ACTIVE
    confidence: Confidence = 1.0

    created_at: float = Field(
        default_factory=time.time,
        description="When this Memory record was created (persisted for "
        "the first time), in Unix seconds. Never mutated after "
        "construction.",
    )
    observed_at: Optional[float] = Field(
        default=None,
        description="When the underlying event/observation this Memory "
        "records actually happened, in Unix seconds -- distinct from "
        "`created_at` because a Memory can be formed well after the "
        "fact (e.g. a REFLECTION-provenance memory summarizing an "
        "episode from earlier). `None` when there is no single "
        "observable instant (e.g. a USER_INPUT preference with no "
        "specific occurrence time).",
    )
    updated_at: float = Field(
        default_factory=time.time,
        description="When this Memory record was last modified. Set equal "
        "to `created_at` at construction; `MemoryManager.update()` is "
        "responsible for refreshing it on every update -- this module "
        "does not do so on its own, since a plain field assignment "
        "(`memory.status = ...`) has no way to know an update is "
        "happening.",
    )

    episode_id: Optional[str] = Field(
        default=None,
        description="Associates this Memory with one execution episode -- "
        "expected to be an `execution.models.ExecutionRecord."
        "execution_id` for EXECUTION-provenance memories. `None` for a "
        "memory with no single originating episode (e.g. a USER "
        "preference).",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Associates this Memory with one task -- expected to "
        "be a `schemas.task.SingleTask.task_id` (echoed through "
        "`planner.models.Plan.task_id` and `execution.models."
        "ExecutionRecord.task_id`). `None` when not applicable.",
    )

    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Open, type-specific auxiliary data not yet promoted "
        "to a first-class field -- see this module's docstring for the "
        "escalation path. Persisted as JSON by every `MemoryStore` "
        "implementation; never the primary representation of this "
        "Memory's content (that is always `content`).",
    )

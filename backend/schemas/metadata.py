"""
metadata.py

Purpose
-------
Defines `TaskMetadata`: the record of *how and when* a `Task` came
into existence, kept separate from the task's own semantic fields
(`goal`, `object`, `priority`, ...). Also defines `SCHEMA_VERSION`, the
single source of truth for which revision of the Language Interface a
given `Task` payload was constructed against.

Why this is a separate file from `task.py`
--------------------------------------------
`Task` answers "what does the user want?"; `TaskMetadata` answers
"where did this record come from, and against which schema revision
should a consumer interpret it?". Those are different concerns with
different lifecycles -- `Task`'s shape changes as the Language
Interface grows new semantic fields (Phase 3.2, 3.3, ...), while
`TaskMetadata`'s shape changes far more rarely, only when the
schema-versioning or provenance story itself changes. Splitting them
into separate files means a change to one never touches the other's
diff, and a future module that only cares about provenance (e.g. a
Memory module deciding whether to re-validate old records after a
schema bump) can import `TaskMetadata` without pulling in the entire
task model graph.

Why schema versioning exists at all
--------------------------------------
No Planner, Memory, or Execution module exists yet to consume
`Task` records, but Memory (Phase 5) is explicitly expected to persist
them long-term. A persisted record written against today's schema must
remain interpretable after the schema evolves. Stamping every `Task`
with the schema revision it was built against, at construction time,
means a future Memory module can detect "this record predates field X"
and handle migration explicitly, instead of guessing from field
presence/absence. `SCHEMA_VERSION` follows semantic versioning: bump
the patch digit for documentation-only or validation-tightening
changes, the minor digit for additive (backward-compatible) field
additions, and the major digit only for a breaking change to this
interface (see `language_interface_spec.md` section 14, "Future
Compatibility").

Downstream consumers
---------------------
- Memory (Phase 5): the primary consumer -- persisted records carry
  `TaskMetadata` so historical data remains interpretable as the schema
  evolves.
- Reflection: `created_at` gives a timestamp to correlate a task
  against the `Scene` state that existed when it was issued.
- Any future audit/debugging tooling: `source` records which producer
  (a specific parser prompt version, a test fixture, a manual
  construction) created a given `Task`, without requiring that producer
  to be inferred from context.
"""

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# Semantic version of the Language Interface schema (schemas/task.py,
# schemas/enums.py, schemas/metadata.py, schemas/validators.py taken
# together). This is the version every `Task` is stamped with unless a
# producer explicitly overrides it (e.g. a fixture reconstructing an
# older record for a migration test). Bump this alongside any schema
# change and record the change in `language_interface_spec.md` section
# 14 -- the version number is only useful if it is actually kept in
# sync with what changed.
SCHEMA_VERSION = "1.0.0"


class TaskMetadata(BaseModel):
    """
    Provenance and versioning record attached to every `Task`.

    Purpose
        Answer "when was this task created, against which schema
        revision, and by what producer?" -- questions no semantic field
        on `Task` itself (`goal`, `priority`, ...) can answer, and that
        become important the moment a `Task` outlives the process that
        created it (i.e. once Memory, Phase 5, persists one).

    Responsibilities
        Hold exactly the three fields above and nothing else. This
        model deliberately does not grow task-specific fields --
        anything describing *what* the task is belongs on `Task` in
        `schemas/task.py`, not here.

    Downstream consumers
        Memory (persistence + schema-migration decisions), Reflection
        (timestamp correlation against `Scene` state), and any future
        audit tooling that needs to know which producer created a given
        record.

    Design notes
        Frozen (`model_config.frozen=True`): a task's provenance is a
        historical fact fixed at the moment of creation. Nothing about
        *when* or *how* a task was constructed should change after the
        fact -- if a task needs to be re-derived, a new `TaskMetadata`
        (with a fresh `created_at`) should be created for the new
        `Task`, not this one mutated in place.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(
        default_factory=lambda: SCHEMA_VERSION,
        description="The Language Interface schema revision this task "
        "was constructed against. Defaults to the current "
        "`SCHEMA_VERSION`; a producer reconstructing an older record "
        "(e.g. in a migration test) may override this explicitly.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp at which this task was constructed. "
        "Used by Reflection to correlate a task against the `Scene` "
        "state that existed when it was issued, and by Memory for "
        "chronological ordering of task history.",
    )
    source: Optional[str] = Field(
        default=None,
        description="Identifier for whatever produced this task (e.g. "
        "a parser prompt version string, 'manual', or a test fixture "
        "name). `None` when the producer did not identify itself. "
        "Purely descriptive -- no downstream module should branch on "
        "this field's value, only log or display it.",
    )

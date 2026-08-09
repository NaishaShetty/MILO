"""
exceptions.py (backend/memory)

Purpose
-------
The closed hierarchy of exceptions this package raises -- mirrors
`execution/exceptions.py` and `planner/exceptions.py`'s split exactly:
every exception here signals a programmer/configuration/data-integrity
problem the caller must handle explicitly (a missing memory, a
duplicate id, a store that failed to initialize), never an ordinary
"no memories matched" outcome, which is just an empty list returned
from `list()`.
"""

from __future__ import annotations


class MemoryError(Exception):
    """Base class for every exception raised by `backend/memory/`."""


class MemoryNotFoundError(MemoryError):
    """
    Raised by `update()`/`delete()` when asked to act on a
    `memory_id` that does not exist in the store. `get()` never raises
    this -- it returns `None` for a missing id, since "does this memory
    exist" is an ordinary lookup outcome, not an error.
    """


class DuplicateMemoryError(MemoryError):
    """
    Raised by `store()` when a `Memory.memory_id` already exists in the
    store. `Memory.memory_id` is generated as a UUID by default (see
    `models.Memory`), so this is expected to be rare -- it exists to
    fail loudly on a genuine id collision (e.g. a caller re-storing the
    same in-memory `Memory` object twice) rather than silently
    overwriting a previous memory's content.
    """


class MemoryStoreError(MemoryError):
    """
    Raised when a storage backend fails for a reason unrelated to the
    specific memory being operated on -- schema initialization failure,
    a corrupted/incompatible on-disk record that cannot be reconstructed
    into a `Memory`, or an unexpected backend (e.g. sqlite3) error.
    """

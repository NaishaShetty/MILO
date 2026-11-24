"""
security.py (backend/api)

Purpose
-------
Two optional guards for the routes that run jobs or change things (the
task, lab and memory routers). Both are **off unless configured**, so a
local demo needs no setup:

- **API key** -- set `API_KEY` and every guarded request must send it in an
  `X-API-Key` header (compared in constant time). The two server-sent-event
  `/stream` routes also accept `?api_key=...`, because a browser's
  `EventSource` cannot set headers; keep that key out of logs if you use it.
  Unset = no key needed.
- **Rate limit** -- set `RATE_LIMIT_PER_MINUTE=N` and each caller (their API
  key if they sent one, else their IP) gets at most N guarded requests in
  any rolling 60 seconds; beyond that, `429` with a `Retry-After` header.
  Unset or `0` = unlimited.

Both read the environment at request time (not import time), so they can be
switched on in tests or a running deployment without a re-import.

Errors use this API's usual `{"category", "message"}` shape, with messages
written to be shown to the person as-is.
"""

from __future__ import annotations

import hmac
import os
import threading
import time
from collections import deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request

_WINDOW_SECONDS = 60.0


def _configured_key() -> Optional[str]:
    value = os.environ.get("API_KEY", "").strip()
    return value or None


def _rate_limit() -> int:
    raw = os.environ.get("RATE_LIMIT_PER_MINUTE", "").strip()
    try:
        return max(int(raw), 0) if raw else 0
    except ValueError:
        return 0


def _supplied_key(request: Request) -> Optional[str]:
    header = request.headers.get("x-api-key")
    if header:
        return header
    if request.url.path.endswith("/stream"):
        return request.query_params.get("api_key")
    return None


async def require_api_key(request: Request) -> None:
    """FastAPI dependency: 401 unless the configured key was sent. A no-op
    when `API_KEY` is not set."""
    expected = _configured_key()
    if expected is None:
        return
    supplied = _supplied_key(request)
    if supplied is None or not hmac.compare_digest(
        supplied.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(
            status_code=401,
            detail={
                "category": "unauthorized",
                "message": "MILO needs the API key for this. Add it in Settings "
                "(it is sent as the X-API-Key header), then try again.",
            },
        )


class SlidingWindowLimiter:
    """At most `limit` hits per key in any rolling `window` seconds."""

    def __init__(self, window: float = _WINDOW_SECONDS) -> None:
        self._window = window
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, now: Optional[float] = None) -> Optional[float]:
        """Records a hit. Returns `None` if allowed, else the seconds to wait."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self._window:
                hits.popleft()
            if len(hits) >= limit:
                return max(self._window - (now - hits[0]), 0.0)
            hits.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


async def rate_limit(request: Request) -> None:
    """FastAPI dependency: 429 past `RATE_LIMIT_PER_MINUTE`. A no-op when
    unset."""
    limit = _rate_limit()
    if limit <= 0:
        return
    who = _supplied_key(request) or (request.client.host if request.client else "?")
    wait = limiter.hit(who, limit)
    if wait is not None:
        seconds = max(int(wait) + 1, 1)
        raise HTTPException(
            status_code=429,
            detail={
                "category": "rate_limited",
                "message": f"That's a lot of requests at once. Please wait "
                f"{seconds} second{'s' if seconds != 1 else ''} and try again.",
            },
            headers={"Retry-After": str(seconds)},
        )

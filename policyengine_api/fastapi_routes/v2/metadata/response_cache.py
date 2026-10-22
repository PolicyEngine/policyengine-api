"""A bounded, process-wide store of whole catalog-version response bodies."""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.responses import JSONResponse

ResponseKey = tuple[str, str, str | None]
"""A route name, a country ID and the requested PolicyEngine.py version.

A version of None means the running version, which is fixed for the process.
"""

DEFAULT_RESPONSE_CAPACITY = 8


class MetadataResponseCache:
    """Keep the serialized bodies of whole-version responses, built once each.

    A published catalog version never changes, so a body built for a route,
    country and version stays valid for the life of the process. The most
    recently used ``capacity`` bodies are kept. Requests for a body being built
    wait for that build instead of starting another, and a failed read (a v2
    error response) is returned but not kept, so the next request tries again.
    """

    def __init__(self, *, capacity: int = DEFAULT_RESPONSE_CAPACITY) -> None:
        """Keep at most ``capacity`` bodies (at least one)."""
        if capacity < 1:
            msg = "capacity must be positive"
            raise ValueError(msg)
        self._capacity = capacity
        self._bodies: OrderedDict[ResponseKey, bytes] = OrderedDict()
        self._lock = threading.Lock()
        self._build_locks: dict[ResponseKey, threading.Lock] = {}

    def _stored(self, key: ResponseKey) -> bytes | None:
        with self._lock:
            body = self._bodies.get(key)
            if body is not None:
                self._bodies.move_to_end(key)
            return body

    def get_or_build(
        self,
        key: ResponseKey,
        build: Callable[[], bytes | JSONResponse],
    ) -> bytes | JSONResponse:
        """Return the body kept for ``key``, calling ``build`` only when none is."""
        body = self._stored(key)
        if body is not None:
            return body
        with self._lock:
            build_lock = self._build_locks.setdefault(key, threading.Lock())
        with build_lock:
            body = self._stored(key)
            if body is not None:
                return body
            built = build()
            with self._lock:
                self._build_locks.pop(key, None)
                if isinstance(built, bytes):
                    self._bodies[key] = built
                    self._bodies.move_to_end(key)
                    while len(self._bodies) > self._capacity:
                        self._bodies.popitem(last=False)
            return built

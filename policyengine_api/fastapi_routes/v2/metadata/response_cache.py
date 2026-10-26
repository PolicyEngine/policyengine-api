"""A bounded, process-wide store of whole catalog-version responses."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from starlette.responses import JSONResponse

DEFAULT_RESPONSE_CAPACITY = 8

KeptResponseKey = tuple[str, str, str]
"""A route name, a country ID and the exact PolicyEngine.py version served."""


def body_entity_tag(body: bytes) -> str:
    """Return the strong ETag of a response body: a hash of its exact bytes."""
    return f'"{hashlib.sha256(body).hexdigest()[:32]}"'


@dataclass(frozen=True)
class BuiltResponse:
    """A serialized success body and the catalog version it was read from."""

    body: bytes
    policyengine_version: str


@dataclass(frozen=True)
class KeptResponse:
    """A kept success body with its ETag, computed once when it was kept."""

    body: bytes
    entity_tag: str


class MetadataResponseCache:
    """Keep whole-version responses, built once each per process.

    A published catalog version never changes, so a body built for a route,
    country and version stays valid for the life of the process. Responses
    are kept under the exact version they were read from: a request without a
    version (the running version, fixed for the process) and one naming that
    version share one response. The most recently used ``capacity`` responses
    are kept. Requests for a response being built wait for that build instead
    of starting another, and a failed read (a v2 error response) is returned
    but not kept, so the next request tries again.
    """

    def __init__(self, *, capacity: int = DEFAULT_RESPONSE_CAPACITY) -> None:
        """Keep at most ``capacity`` responses (at least one)."""
        if capacity < 1:
            msg = "capacity must be positive"
            raise ValueError(msg)
        self._capacity = capacity
        self._responses: OrderedDict[KeptResponseKey, KeptResponse] = OrderedDict()
        self._running_versions: dict[tuple[str, str], str] = {}
        self._lock = threading.Lock()
        self._build_locks: dict[tuple[str, str, str | None], threading.Lock] = {}

    def _stored(
        self, route: str, country_id: str, requested_version: str | None
    ) -> KeptResponse | None:
        with self._lock:
            version = (
                requested_version
                if requested_version is not None
                else self._running_versions.get((route, country_id))
            )
            if version is None:
                return None
            key = (route, country_id, version)
            kept = self._responses.get(key)
            if kept is not None:
                self._responses.move_to_end(key)
            return kept

    def get_or_build(
        self,
        route: str,
        country_id: str,
        requested_version: str | None,
        build: Callable[[], BuiltResponse | JSONResponse],
    ) -> KeptResponse | JSONResponse:
        """Return the kept response, calling ``build`` only when none is kept.

        ``requested_version`` None means the running version.
        """
        kept = self._stored(route, country_id, requested_version)
        if kept is not None:
            return kept
        build_key = (route, country_id, requested_version)
        with self._lock:
            build_lock = self._build_locks.setdefault(build_key, threading.Lock())
        with build_lock:
            kept = self._stored(route, country_id, requested_version)
            if kept is not None:
                return kept
            built = build()
            with self._lock:
                self._build_locks.pop(build_key, None)
            if not isinstance(built, BuiltResponse):
                return built
            return self._keep(route, country_id, requested_version, built)

    def _keep(
        self,
        route: str,
        country_id: str,
        requested_version: str | None,
        built: BuiltResponse,
    ) -> KeptResponse:
        key = (route, country_id, built.policyengine_version)
        with self._lock:
            if requested_version is None:
                self._running_versions[(route, country_id)] = built.policyengine_version
            kept = self._responses.get(key)
            if kept is None:
                kept = KeptResponse(
                    body=built.body, entity_tag=body_entity_tag(built.body)
                )
                self._responses[key] = kept
            self._responses.move_to_end(key)
            while len(self._responses) > self._capacity:
                self._responses.popitem(last=False)
            return kept

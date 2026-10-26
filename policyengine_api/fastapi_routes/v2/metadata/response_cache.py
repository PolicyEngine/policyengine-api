"""A bounded, process-wide store of whole catalog-version responses."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.responses import Response

if TYPE_CHECKING:
    from collections.abc import Callable

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


@dataclass(frozen=True)
class FailedRead:
    """A failed whole-version read, given to the requests that waited on it."""

    status_code: int
    body: bytes

    def response(self) -> Response:
        """Return a new error response for one waiting request.

        Each request gets its own response object, because middleware adds
        request-specific headers to the response it sends.
        """
        return Response(
            content=self.body,
            status_code=self.status_code,
            media_type="application/json",
        )


class _InFlightRead:
    """One read in progress for a key, and how many requests wait on it."""

    def __init__(self) -> None:
        self.done = threading.Event()
        self.outcome: KeptResponse | FailedRead | None = None
        self.waiters = 0


class MetadataResponseCache:
    """Keep whole-version responses, built once each per process.

    A published catalog version never changes, so a body built for a route,
    country and version stays valid for the life of the process. Responses
    are kept under the exact version they were read from: a request without a
    version (the running version, fixed for the process) and one naming that
    version share one response. The most recently used ``capacity`` responses
    are kept: the US variables body of the 6.10.0 catalog is 4,190,824 bytes
    uncompressed, so the default of eight holds about 12 MB for both
    countries' two whole-version routes at two versions, and at most about
    34 MB if every entry were that large. Requests that arrive while a read
    for the same key is in progress wait for it, and all receive its outcome:
    the kept response, or a copy of its error response. A failed read is not
    kept, so the first request after it reads again.
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
        self._builds: dict[tuple[str, str, str | None], _InFlightRead] = {}

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
        build: Callable[[], BuiltResponse | Response],
    ) -> KeptResponse | Response:
        """Return the kept response, calling ``build`` only when none is kept.

        ``requested_version`` None means the running version. Requests that
        arrive while a read for the same key is in progress wait for it and
        receive its outcome: the kept response, or a copy of its error
        response. A failed read is not kept, so the next request after it
        reads again.
        """
        kept = self._stored(route, country_id, requested_version)
        if kept is not None:
            return kept
        key = (route, country_id, requested_version)
        with self._lock:
            in_flight = self._builds.get(key)
            if in_flight is None:
                in_flight = _InFlightRead()
                self._builds[key] = in_flight
                reads_itself = True
            else:
                in_flight.waiters += 1
                reads_itself = False
        if not reads_itself:
            in_flight.done.wait()
            outcome = in_flight.outcome
            if outcome is None:
                # The read raised instead of returning a response: try again.
                return self.get_or_build(route, country_id, requested_version, build)
            return outcome.response() if isinstance(outcome, FailedRead) else outcome
        try:
            kept = self._stored(route, country_id, requested_version)
            if kept is None:
                built = build()
                if not isinstance(built, BuiltResponse):
                    in_flight.outcome = FailedRead(
                        status_code=built.status_code, body=bytes(built.body)
                    )
                    return built
                kept = self._keep(route, country_id, requested_version, built)
            in_flight.outcome = kept
            return kept
        finally:
            with self._lock:
                # Only this read's own entry is removed; a later read for the
                # same key keeps its entry.
                if self._builds.get(key) is in_flight:
                    del self._builds[key]
            in_flight.done.set()

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

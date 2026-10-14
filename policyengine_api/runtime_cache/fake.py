"""Deterministic in-memory cache backend for pure unit tests only."""

from __future__ import annotations

from threading import RLock
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Callable


class InMemoryCacheBackend:
    """Small Redis-like fake with explicit time advancement and atomic pipelines."""

    def __init__(self, *, now: Callable[[], float] | None = None) -> None:
        """Start empty at time zero, or follow the ``now`` clock when one is given."""
        self._external_now = now
        self._time = 0.0
        self._values: dict[str, str] = {}
        self._expires: dict[str, float] = {}
        self._sorted_sets: dict[str, dict[str, float]] = {}
        self._lock = RLock()

    def _now(self) -> float:
        return self._external_now() if self._external_now else self._time

    def advance(self, seconds: float) -> None:
        """Move the fake clock forward so TTLs can expire without sleeping.

        Raises RuntimeError when the fake follows an external clock instead.
        """
        if self._external_now is not None:
            msg = "cannot advance an externally clocked fake"
            raise RuntimeError(msg)
        self._time += seconds

    def _purge(self, key: str) -> None:
        expires_at = self._expires.get(key)
        if expires_at is not None and expires_at <= self._now():
            self._values.pop(key, None)
            self._sorted_sets.pop(key, None)
            self._expires.pop(key, None)

    def get(self, key: str) -> str | None:
        """Emulate GET: return the string value, or None if missing or expired."""
        with self._lock:
            self._purge(key)
            return self._values.get(key)

    def set(
        self,
        key: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        """Emulate SET with the ``ex`` and ``nx`` options only.

        Like redis-py, return True on a write and None when ``nx`` finds the key
        already set; a write without ``ex`` clears any earlier TTL.
        """
        with self._lock:
            self._purge(key)
            if nx and key in self._values:
                return None
            self._values[key] = value
            if ex is not None:
                self._expires[key] = self._now() + ex
            else:
                self._expires.pop(key, None)
            return True

    def delete(self, *keys: str) -> int:
        """Emulate DEL for strings and sorted sets, returning how many existed."""
        with self._lock:
            deleted = 0
            for key in keys:
                self._purge(key)
                if key in self._values or key in self._sorted_sets:
                    deleted += 1
                self._values.pop(key, None)
                self._sorted_sets.pop(key, None)
                self._expires.pop(key, None)
            return deleted

    def expire(self, key: str, seconds: int) -> bool:
        """Emulate EXPIRE: set a TTL and return False if the key does not exist."""
        with self._lock:
            self._purge(key)
            if key not in self._values and key not in self._sorted_sets:
                return False
            self._expires[key] = self._now() + seconds
            return True

    def zadd(self, key: str, mapping: dict[str, float]) -> int:
        """Emulate ZADD without flags: upsert scores and count new members only."""
        with self._lock:
            self._purge(key)
            values = self._sorted_sets.setdefault(key, {})
            added = sum(member not in values for member in mapping)
            values.update(mapping)
            return added

    def zrevrange(self, key: str, start: int, end: int) -> list[str]:
        """Emulate ZREVRANGE: members by descending score over inclusive ranks.

        Equal scores fall back to reverse member order, as in Redis. The only
        negative ``end`` supported is ``-1`` (the last member).
        """
        with self._lock:
            self._purge(key)
            ordered = sorted(
                self._sorted_sets.get(key, {}).items(),
                key=lambda item: (item[1], item[0]),
                reverse=True,
            )
            stop = None if end == -1 else end + 1
            return [member for member, _ in ordered[start:stop]]

    def zrem(self, key: str, *members: str) -> int:
        """Emulate ZREM, returning how many of the members were present."""
        with self._lock:
            values = self._sorted_sets.get(key, {})
            removed = sum(member in values for member in members)
            for member in members:
                values.pop(member, None)
            return removed

    def zremrangebyrank(self, key: str, start: int, end: int) -> int:
        """Emulate ZREMRANGEBYRANK over ascending-score ranks, inclusive of ``end``.

        As with ``zrevrange``, the only negative ``end`` supported is ``-1``.
        """
        with self._lock:
            self._purge(key)
            ordered = sorted(
                self._sorted_sets.get(key, {}).items(),
                key=lambda item: (item[1], item[0]),
            )
            stop = None if end == -1 else end + 1
            members = [member for member, _ in ordered[start:stop]]
            return self.zrem(key, *members)

    def eval(
        self,
        _script: str,
        numkeys: int,
        *keys_and_args: str,
    ) -> int:
        """Emulate EVAL of the claim store's compare-and-delete script only.

        The script text is ignored: delete the one key if it still holds the
        expected token, and raise ValueError for any other key/argument shape.
        """
        if numkeys != 1 or len(keys_and_args) != 2:
            msg = "fake supports one-key compare-and-delete only"
            raise ValueError(msg)
        key, expected = keys_and_args
        with self._lock:
            if self.get(key) != expected:
                return 0
            return self.delete(key)

    def pipeline(self, transaction: bool = True) -> InMemoryPipeline:
        """Return a pipeline that queues commands until ``execute``."""
        return InMemoryPipeline(self, transaction=transaction)


class InMemoryPipeline:
    """A fake Redis pipeline that records any method call and replays it later."""

    def __init__(self, backend: InMemoryCacheBackend, *, transaction: bool) -> None:
        """Queue commands for ``backend``; ``transaction`` makes ``execute`` atomic."""
        self.backend = backend
        self.transaction = transaction
        self.operations: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def __getattr__(self, name: str) -> Callable[..., InMemoryPipeline]:
        """Return a recorder that queues a call to the backend method ``name``."""

        def queue(*args: object, **kwargs: object) -> InMemoryPipeline:
            self.operations.append((name, args, kwargs))
            return self

        return queue

    def execute(self) -> list[object]:
        """Replay the queued commands on the backend, then clear the queue.

        With ``transaction`` the replay holds the backend lock, as MULTI/EXEC
        would; without it, other callers' commands may interleave.
        """
        lock = self.backend._lock if self.transaction else RLock()  # noqa: SLF001  # a transactional replay holds the backend lock, as MULTI/EXEC would
        with lock:
            results = [
                getattr(self.backend, name)(*args, **kwargs)
                for name, args, kwargs in self.operations
            ]
        self.operations.clear()
        return results

    def __enter__(self) -> Self:
        """Return the pipeline itself for use in a ``with`` block."""
        return self

    def __exit__(self, *_args: object) -> None:
        """Drop queued commands that were never executed."""
        self.operations.clear()


class DisabledCacheBackend(InMemoryCacheBackend):
    """No-storage backend for unselected unit-test/application cache mode."""

    def get(self, key: str) -> None:
        """Return None: every read is a miss."""

    def set(self, key: str, value: str, **_kwargs: object) -> bool:  # noqa: ARG002  # overrides InMemoryCacheBackend.set
        """Discard the value and report the write as not stored."""
        return False

    def delete(self, *_keys: str) -> int:
        """Return 0: no key ever exists."""
        return 0

    def zadd(self, key: str, mapping: dict[str, float]) -> int:  # noqa: ARG002  # overrides InMemoryCacheBackend.zadd
        """Discard the members and report none added."""
        return 0

    def zrevrange(self, key: str, start: int, end: int) -> list[str]:  # noqa: ARG002  # overrides InMemoryCacheBackend.zrevrange
        """Return an empty list: no sorted set ever exists."""
        return []

    def zrem(self, key: str, *_members: str) -> int:  # noqa: ARG002  # overrides InMemoryCacheBackend.zrem
        """Return 0: there is nothing to remove."""
        return 0

    def zremrangebyrank(self, key: str, start: int, end: int) -> int:  # noqa: ARG002  # overrides InMemoryCacheBackend.zremrangebyrank
        """Return 0: there is nothing to remove."""
        return 0

    def expire(self, key: str, seconds: int) -> bool:  # noqa: ARG002  # overrides InMemoryCacheBackend.expire
        """Return False, as Redis does for a key that does not exist."""
        return False

    def eval(
        self,
        _script: str,
        numkeys: int,  # noqa: ARG002  # overrides InMemoryCacheBackend.eval
        *_keys_and_args: str,
    ) -> int:
        """Raise RuntimeError, so claim operations fail closed when disabled."""
        msg = "the shared runtime cache is disabled"
        raise RuntimeError(msg)

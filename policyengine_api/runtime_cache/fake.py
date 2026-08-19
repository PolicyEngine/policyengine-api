"""Deterministic in-memory cache backend for pure unit tests only."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Any


class InMemoryCacheBackend:
    """Small Redis-like fake with explicit time advancement and atomic pipelines."""

    def __init__(self, *, now: Callable[[], float] | None = None) -> None:
        self._external_now = now
        self._time = 0.0
        self._values: dict[str, Any] = {}
        self._expires: dict[str, float] = {}
        self._sorted_sets: dict[str, dict[str, float]] = {}
        self._lock = RLock()

    def _now(self) -> float:
        return self._external_now() if self._external_now else self._time

    def advance(self, seconds: float) -> None:
        if self._external_now is not None:
            raise RuntimeError("cannot advance an externally clocked fake")
        self._time += seconds

    def _purge(self, key: str) -> None:
        expires_at = self._expires.get(key)
        if expires_at is not None and expires_at <= self._now():
            self._values.pop(key, None)
            self._sorted_sets.pop(key, None)
            self._expires.pop(key, None)

    def get(self, key: str) -> Any:
        with self._lock:
            self._purge(key)
            return self._values.get(key)

    def set(
        self,
        key: str,
        value: Any,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None:
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
        with self._lock:
            self._purge(key)
            if key not in self._values and key not in self._sorted_sets:
                return False
            self._expires[key] = self._now() + seconds
            return True

    def zadd(self, key: str, mapping: dict[str, float]) -> int:
        with self._lock:
            self._purge(key)
            values = self._sorted_sets.setdefault(key, {})
            added = sum(member not in values for member in mapping)
            values.update(mapping)
            return added

    def zrevrange(self, key: str, start: int, end: int) -> list[str]:
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
        with self._lock:
            values = self._sorted_sets.get(key, {})
            removed = sum(member in values for member in members)
            for member in members:
                values.pop(member, None)
            return removed

    def zremrangebyrank(self, key: str, start: int, end: int) -> int:
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
        if numkeys != 1 or len(keys_and_args) != 2:
            raise ValueError("fake supports one-key compare-and-delete only")
        key, expected = keys_and_args
        with self._lock:
            if self.get(key) != expected:
                return 0
            return self.delete(key)

    def pipeline(self, transaction: bool = True) -> "InMemoryPipeline":
        return InMemoryPipeline(self, transaction=transaction)


class InMemoryPipeline:
    def __init__(self, backend: InMemoryCacheBackend, *, transaction: bool) -> None:
        self.backend = backend
        self.transaction = transaction
        self.operations: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str):
        def queue(*args: Any, **kwargs: Any) -> "InMemoryPipeline":
            self.operations.append((name, args, kwargs))
            return self

        return queue

    def execute(self) -> list[Any]:
        lock = self.backend._lock if self.transaction else RLock()
        with lock:
            results = [
                getattr(self.backend, name)(*args, **kwargs)
                for name, args, kwargs in self.operations
            ]
        self.operations.clear()
        return results

    def __enter__(self) -> "InMemoryPipeline":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.operations.clear()


class DisabledCacheBackend(InMemoryCacheBackend):
    """No-storage backend for unselected unit-test/application cache mode."""

    def get(self, key: str) -> None:
        return None

    def set(self, key: str, value: Any, **kwargs: Any) -> bool:
        return False

    def delete(self, *keys: str) -> int:
        return 0

    def zadd(self, key: str, mapping: dict[str, float]) -> int:
        return 0

    def zrevrange(self, key: str, start: int, end: int) -> list[str]:
        return []

    def zrem(self, key: str, *members: str) -> int:
        return 0

    def zremrangebyrank(self, key: str, start: int, end: int) -> int:
        return 0

    def expire(self, key: str, seconds: int) -> bool:
        return False

    def eval(
        self,
        _script: str,
        numkeys: int,
        *keys_and_args: str,
    ) -> int:
        raise RuntimeError("the shared runtime cache is disabled")

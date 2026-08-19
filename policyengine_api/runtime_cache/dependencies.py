"""Lazy default cache backend and namespace dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from policyengine_api.runtime_cache.client import get_runtime_cache_client
from policyengine_api.runtime_cache.core import CacheBackend, CacheNamespace
from policyengine_api.runtime_cache.fake import DisabledCacheBackend
from policyengine_api.runtime_cache.settings import load_runtime_cache_settings


@dataclass(frozen=True)
class RuntimeCacheContext:
    client: CacheBackend
    namespace: CacheNamespace
    enabled: bool


@lru_cache(maxsize=1)
def get_runtime_cache_context() -> RuntimeCacheContext:
    settings = load_runtime_cache_settings()
    namespace = CacheNamespace(settings.environment, settings.service)
    client: CacheBackend = (
        get_runtime_cache_client(settings)
        if settings.enabled
        else DisabledCacheBackend()
    )
    return RuntimeCacheContext(
        client=client,
        namespace=namespace,
        enabled=settings.enabled,
    )


def clear_runtime_cache_context() -> None:
    get_runtime_cache_context.cache_clear()

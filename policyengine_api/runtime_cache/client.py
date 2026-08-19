"""Lazy, process-owned Redis client construction."""

from __future__ import annotations

import os
from threading import Lock
from typing import Any

import redis

from policyengine_api.runtime_cache.settings import (
    RuntimeCacheSettings,
    load_runtime_cache_settings,
)


_clients: dict[int, redis.Redis] = {}
_client_lock = Lock()


def build_runtime_cache_client(settings: RuntimeCacheSettings) -> redis.Redis:
    if not settings.enabled or settings.url is None:
        raise RuntimeError("the shared runtime cache is disabled")
    kwargs: dict[str, Any] = {
        "decode_responses": True,
        "max_connections": settings.max_connections,
        "socket_connect_timeout": settings.connect_timeout_seconds,
        "socket_timeout": settings.operation_timeout_seconds,
        "health_check_interval": 30,
        "retry_on_timeout": False,
    }
    if settings.tls:
        kwargs["ssl_cert_reqs"] = "required"
        if settings.ca_cert is None:
            raise RuntimeError("the shared runtime cache TLS CA is missing")
        kwargs["ssl_ca_data"] = settings.ca_cert.get_secret_value()
    return redis.Redis.from_url(settings.url.get_secret_value(), **kwargs)


def get_runtime_cache_client(
    settings: RuntimeCacheSettings | None = None,
) -> redis.Redis:
    """Return one client per process without connecting during import."""

    process_id = os.getpid()
    if process_id not in _clients:
        with _client_lock:
            if process_id not in _clients:
                _clients[process_id] = build_runtime_cache_client(
                    settings or load_runtime_cache_settings()
                )
    return _clients[process_id]


def close_runtime_cache_clients() -> None:
    for client in _clients.values():
        client.close()
    _clients.clear()

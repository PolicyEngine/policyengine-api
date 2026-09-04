"""Whether the API has finished warming up and can serve real requests.

Defaults to ready, so tests and tooling that do not run a startup warmup report
ready immediately. The Cloud Run startup path toggles it around the warmup
(`policyengine_api.warmup`).
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_ready = True


def validate_policy_runtime_configuration() -> None:
    """Validate Phase 10 policy sources and conditionally require Supabase."""

    from policyengine_api.data.v2.settings import (
        load_v2_runtime_database_settings,
    )
    from policyengine_api.migration_flags import (
        RouteImplementation,
        get_route_impl,
        get_v1_policy_read_source,
        get_v1_policy_write_source,
    )

    write_source = get_v1_policy_write_source()
    get_v1_policy_read_source()
    native_policy_routes = (
        get_route_impl("policy") is RouteImplementation.FASTAPI_NATIVE
    )
    if write_source == "dual_write" or native_policy_routes:
        load_v2_runtime_database_settings()


def mark_not_ready() -> None:
    """Report not-ready — call before running the startup warmup."""
    global _ready
    with _lock:
        _ready = False


def mark_ready() -> None:
    """Report ready — call once the startup warmup has completed."""
    global _ready
    with _lock:
        _ready = True


def is_ready() -> bool:
    """Whether the service is warmed up and can serve a real request quickly."""
    with _lock:
        warmed_up = _ready
    if not warmed_up:
        return False
    try:
        validate_policy_runtime_configuration()
    except (RuntimeError, ValueError):
        return False
    return True

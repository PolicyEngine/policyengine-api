"""No-op migration flags for the API v2 migration.

These flags do not change behavior in PR 1. They only give later PRs a stable
configuration surface and give current requests enough context for logging.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from policyengine_api.migration_registry import (
    ROUTE_GROUP_BY_SEGMENT,
    ROUTE_GROUP_CONFIG_BY_NAME,
)


API_HOST_BACKENDS = frozenset({"app_engine", "cloud_run"})
ROUTE_IMPLEMENTATIONS = frozenset({"flask_fallback", "fastapi_native"})
DB_WRITE_SOURCES = frozenset({"cloud_sql", "dual_write", "supabase"})
DB_READ_SOURCES = frozenset({"cloud_sql", "read_compare", "supabase"})
SIM_FRONT_DOORS = frozenset({"old_gateway_direct", "cloud_run_facade"})
SIM_COMPUTE_BACKENDS = frozenset(
    {"old_gateway", "v2_shadow", "v2_percent", "v2_primary"}
)

DEFAULT_API_HOST_BACKEND = "app_engine"
DEFAULT_ROUTE_IMPLEMENTATION = "flask_fallback"
DEFAULT_DB_SOURCE = "cloud_sql"
DEFAULT_SIM_FRONT_DOOR = "old_gateway_direct"
DEFAULT_SIM_COMPUTE_BACKEND = "old_gateway"


@dataclass(frozen=True)
class MigrationContext:
    api_host_backend: str
    route_group: str
    route_impl: str
    db_entity: str | None
    db_write: str | None
    db_read: str | None
    sim_flow: str | None
    sim_front_door: str
    sim_compute: str | None

    def to_log_dict(self) -> dict:
        return {
            "api_host_backend": self.api_host_backend,
            "route_group": self.route_group,
            "route_impl": self.route_impl,
            "db_entity": self.db_entity,
            "db_write": self.db_write,
            "db_read": self.db_read,
            "sim_flow": self.sim_flow,
            "sim_front_door": self.sim_front_door,
            "sim_compute": self.sim_compute,
        }


def _read_choice(env_name: str, default: str, valid_values: frozenset[str]) -> str:
    value = os.environ.get(env_name, default)
    if value not in valid_values:
        choices = ", ".join(sorted(valid_values))
        raise ValueError(f"{env_name}={value!r} is invalid; expected one of: {choices}")
    return value


def infer_route_group(path: str) -> str:
    """Infer a migration route group from a request path."""
    if path in {"/", ""}:
        return "home"
    if path in {
        "/health",
        "/simulation-gateway-check",
        "/liveness-check",
        "/readiness-check",
    }:
        return "health"
    if path == "/specification":
        return "specification"

    segments = [segment for segment in path.strip("/").split("/") if segment]
    if not segments:
        return "home"

    first = segments[0]
    if first in ROUTE_GROUP_BY_SEGMENT:
        return ROUTE_GROUP_BY_SEGMENT[first]

    if len(segments) >= 2 and segments[1] in ROUTE_GROUP_BY_SEGMENT:
        return ROUTE_GROUP_BY_SEGMENT[segments[1]]

    return "unknown"


def get_route_impl(route_group: str) -> str:
    env_name = f"ROUTE_IMPL_{route_group.upper()}"
    return _read_choice(
        env_name,
        DEFAULT_ROUTE_IMPLEMENTATION,
        ROUTE_IMPLEMENTATIONS,
    )


def get_db_write(entity: str) -> str:
    env_name = f"DB_WRITE_{entity.upper()}"
    return _read_choice(env_name, DEFAULT_DB_SOURCE, DB_WRITE_SOURCES)


def get_db_read(entity: str) -> str:
    env_name = f"DB_READ_{entity.upper()}"
    return _read_choice(env_name, DEFAULT_DB_SOURCE, DB_READ_SOURCES)


def get_sim_compute(flow: str) -> str:
    env_name = f"SIM_COMPUTE_{flow.upper()}"
    return _read_choice(
        env_name,
        DEFAULT_SIM_COMPUTE_BACKEND,
        SIM_COMPUTE_BACKENDS,
    )


def get_migration_context(
    route_group: str,
    *,
    db_entity: str | None = None,
    sim_flow: str | None = None,
) -> MigrationContext:
    """Return current migration flag values for a request or route group."""
    route_config = ROUTE_GROUP_CONFIG_BY_NAME.get(route_group)
    if db_entity is None and route_config is not None:
        db_entity = route_config.db_entity
    if sim_flow is None and route_config is not None:
        sim_flow = route_config.sim_flow

    return MigrationContext(
        api_host_backend=_read_choice(
            "API_HOST_BACKEND",
            DEFAULT_API_HOST_BACKEND,
            API_HOST_BACKENDS,
        ),
        route_group=route_group,
        route_impl=get_route_impl(route_group),
        db_entity=db_entity,
        db_write=get_db_write(db_entity) if db_entity else None,
        db_read=get_db_read(db_entity) if db_entity else None,
        sim_flow=sim_flow,
        sim_front_door=_read_choice(
            "SIM_FRONT_DOOR",
            DEFAULT_SIM_FRONT_DOOR,
            SIM_FRONT_DOORS,
        ),
        sim_compute=get_sim_compute(sim_flow) if sim_flow else None,
    )


def get_migration_log_context(route_group: str) -> dict:
    """Best-effort logging context; never raises on invalid flag settings."""
    try:
        return get_migration_context(route_group).to_log_dict()
    except ValueError as error:
        return {
            "route_group": route_group,
            "migration_flag_error": str(error),
        }

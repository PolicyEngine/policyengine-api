"""Typed runtime selectors and request context for the API v2 migration.

The selectors provide independently deployable boundaries for route
implementations, database sources, and simulation routing. Early-stage defaults
preserve the legacy implementation until a deployment opts into a migrated path
explicitly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum

from policyengine_api.migration_registry import (
    ROUTE_GROUP_BY_SEGMENT,
    ROUTE_GROUP_CONFIG_BY_NAME,
)


class RouteImplementation(StrEnum):
    """Available implementations for a migratable API route group."""

    FLASK_FALLBACK = "flask_fallback"
    FASTAPI_NATIVE = "fastapi_native"


ROUTE_IMPLEMENTATIONS = frozenset(
    implementation.value for implementation in RouteImplementation
)
DB_WRITE_SOURCES = frozenset({"cloud_sql", "dual_write", "supabase"})
DB_READ_SOURCES = frozenset({"cloud_sql", "read_compare", "supabase"})
V1_POLICY_WRITE_SOURCES = frozenset({"cloud_sql", "dual_write"})
V1_POLICY_READ_SOURCES = frozenset({"cloud_sql"})
SIM_ENTRYPOINTS = frozenset({"old_gateway_direct", "cloud_run_simulation_entrypoint"})
SIM_COMPUTE_BACKENDS = frozenset(
    {"old_gateway", "v2_shadow", "v2_percent", "v2_primary"}
)

DEFAULT_ROUTE_IMPLEMENTATION = RouteImplementation.FLASK_FALLBACK
DEFAULT_DB_SOURCE = "cloud_sql"
DEFAULT_SIM_ENTRYPOINT = "old_gateway_direct"
DEFAULT_SIM_COMPUTE_BACKEND = "old_gateway"


@dataclass(frozen=True)
class MigrationContext:
    route_group: str
    route_impl: RouteImplementation
    db_entity: str | None
    db_write: str | None
    db_read: str | None
    sim_flow: str | None
    sim_entrypoint: str
    sim_compute: str | None

    def to_log_dict(self) -> dict:
        return {
            "route_group": self.route_group,
            "route_impl": self.route_impl.value,
            "db_entity": self.db_entity,
            "db_write": self.db_write,
            "db_read": self.db_read,
            "sim_flow": self.sim_flow,
            "sim_entrypoint": self.sim_entrypoint,
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
    if path in {"/specification", "/v2/openapi.json"}:
        return "specification"

    segments = [segment for segment in path.strip("/").split("/") if segment]
    if not segments:
        return "home"

    first = segments[0]
    if first in ROUTE_GROUP_BY_SEGMENT:
        return ROUTE_GROUP_BY_SEGMENT[first]

    if len(segments) >= 2 and segments[1] in ROUTE_GROUP_BY_SEGMENT:
        return ROUTE_GROUP_BY_SEGMENT[segments[1]]

    if first == "v2" and len(segments) >= 3 and segments[2] in ROUTE_GROUP_BY_SEGMENT:
        return ROUTE_GROUP_BY_SEGMENT[segments[2]]

    return "unknown"


def get_route_impl(route_group: str) -> RouteImplementation:
    env_name = f"ROUTE_IMPL_{route_group.upper()}"
    return RouteImplementation(
        _read_choice(
            env_name,
            DEFAULT_ROUTE_IMPLEMENTATION.value,
            ROUTE_IMPLEMENTATIONS,
        )
    )


@dataclass(frozen=True)
class RouteImplementationSettings:
    """Startup route selections for the read groups migrated in Stage 6."""

    health: RouteImplementation
    specification: RouteImplementation
    metadata: RouteImplementation

    @classmethod
    def from_environment(cls) -> "RouteImplementationSettings":
        """Read and validate each Stage 6 route selector independently."""
        return cls(
            health=get_route_impl("health"),
            specification=get_route_impl("specification"),
            metadata=get_route_impl("metadata"),
        )


def get_db_write(entity: str) -> str:
    env_name = f"DB_WRITE_{entity.upper()}"
    return _read_choice(env_name, DEFAULT_DB_SOURCE, DB_WRITE_SOURCES)


def get_db_read(entity: str) -> str:
    env_name = f"DB_READ_{entity.upper()}"
    return _read_choice(env_name, DEFAULT_DB_SOURCE, DB_READ_SOURCES)


def get_v1_policy_write_source() -> str:
    """Select Cloud SQL alone or immediate Cloud SQL-to-Supabase mirroring."""

    return _read_choice(
        "DB_WRITE_POLICY",
        DEFAULT_DB_SOURCE,
        V1_POLICY_WRITE_SOURCES,
    )


def get_v1_policy_read_source() -> str:
    """Require every v1 policy read to remain on Cloud SQL in Phase 10."""

    return _read_choice(
        "DB_READ_POLICY",
        DEFAULT_DB_SOURCE,
        V1_POLICY_READ_SOURCES,
    )


def get_sim_compute(flow: str) -> str:
    env_name = f"SIM_COMPUTE_{flow.upper()}"
    return _read_choice(
        env_name,
        DEFAULT_SIM_COMPUTE_BACKEND,
        SIM_COMPUTE_BACKENDS,
    )


def get_sim_entrypoint() -> str:
    """Return the configured API v1-to-simulation-service entrypoint."""
    return _read_choice(
        "SIM_ENTRYPOINT",
        DEFAULT_SIM_ENTRYPOINT,
        SIM_ENTRYPOINTS,
    )


def get_migration_context(
    route_group: str,
    *,
    route_impl: RouteImplementation | None = None,
    db_entity: str | None = None,
    sim_flow: str | None = None,
    use_configured_db_sources: bool = True,
    db_write_source: str | None = None,
    db_read_source: str | None = None,
) -> MigrationContext:
    """Return current migration flag values for a request or route group."""
    route_config = ROUTE_GROUP_CONFIG_BY_NAME.get(route_group)
    if db_entity is None and route_config is not None:
        db_entity = route_config.db_entity
    if sim_flow is None and route_config is not None:
        sim_flow = route_config.sim_flow

    if use_configured_db_sources:
        db_write = get_db_write(db_entity) if db_entity else None
        db_read = get_db_read(db_entity) if db_entity else None
    else:
        if db_write_source is not None and db_write_source not in DB_WRITE_SOURCES:
            raise ValueError(
                f"invalid explicit database write source {db_write_source!r}"
            )
        if db_read_source is not None and db_read_source not in DB_READ_SOURCES:
            raise ValueError(
                f"invalid explicit database read source {db_read_source!r}"
            )
        db_write = db_write_source
        db_read = db_read_source

    return MigrationContext(
        route_group=route_group,
        route_impl=route_impl or get_route_impl(route_group),
        db_entity=db_entity,
        db_write=db_write,
        db_read=db_read,
        sim_flow=sim_flow,
        sim_entrypoint=get_sim_entrypoint(),
        sim_compute=get_sim_compute(sim_flow) if sim_flow else None,
    )


def get_migration_log_context(
    route_group: str,
    *,
    route_impl: RouteImplementation | None = None,
    use_configured_db_sources: bool = True,
    db_write_source: str | None = None,
    db_read_source: str | None = None,
) -> dict:
    """Best-effort logging context; never raises on invalid flag settings."""
    try:
        return get_migration_context(
            route_group,
            route_impl=route_impl,
            use_configured_db_sources=use_configured_db_sources,
            db_write_source=db_write_source,
            db_read_source=db_read_source,
        ).to_log_dict()
    except ValueError as error:
        return {
            "route_group": route_group,
            "migration_flag_error": str(error),
        }

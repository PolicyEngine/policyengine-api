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
V1_HOUSEHOLD_WRITE_SOURCES = frozenset({"cloud_sql", "dual_write"})
V1_HOUSEHOLD_READ_SOURCES = frozenset({"cloud_sql"})
SIM_ENTRYPOINTS = frozenset({"old_gateway_direct", "cloud_run_simulation_entrypoint"})
SIM_COMPUTE_BACKENDS = frozenset(
    {"old_gateway", "v2_shadow", "v2_percent", "v2_primary"}
)

DEFAULT_ROUTE_IMPLEMENTATION = RouteImplementation.FLASK_FALLBACK
DEFAULT_DB_SOURCE = "cloud_sql"
DEFAULT_SIM_ENTRYPOINT = "old_gateway_direct"
DEFAULT_SIM_COMPUTE_BACKEND = "old_gateway"

ROUTE_GROUP_BY_PATH = {
    "": "home",
    "/": "home",
    "/health": "health",
    "/simulation-gateway-check": "health",
    "/liveness-check": "health",
    "/readiness-check": "health",
    "/specification": "specification",
    "/v2/openapi.json": "specification",
}
# Any other path's group is named by one of its leading segments: the resource
# ("/policy"), the resource after a country ("/us/policy") or, under "/v2", the
# resource after the version and a country ("/v2/us/policy").
ROUTE_GROUP_SEGMENT_DEPTH = 2
V2_ROUTE_GROUP_SEGMENT_DEPTH = 3


@dataclass(frozen=True)
class ExplicitDatabaseSources:
    """Database sources a request names itself, in place of the configured flags.

    Each source is validated against the known sources; None records no source.
    """

    db_write_source: str | None = None
    db_read_source: str | None = None


@dataclass(frozen=True)
class MigrationContext:
    """The migration flag values in force for one request, as recorded in its logs."""

    route_group: str
    route_impl: RouteImplementation
    db_entity: str | None
    db_write: str | None
    db_read: str | None
    sim_flow: str | None
    sim_entrypoint: str
    sim_compute: str | None

    def to_log_dict(self) -> dict:
        """Return the flags as a flat log record, with ``route_impl`` as its value."""
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
        msg = f"{env_name}={value!r} is invalid; expected one of: {choices}"
        raise ValueError(msg)
    return value


def infer_route_group(path: str) -> str:
    """Infer a migration route group from a request path."""
    path_group = ROUTE_GROUP_BY_PATH.get(path)
    if path_group is not None:
        return path_group

    segments = [segment for segment in path.strip("/").split("/") if segment]
    if not segments:
        return "home"

    searched_depth = (
        V2_ROUTE_GROUP_SEGMENT_DEPTH
        if segments[0] == "v2"
        else ROUTE_GROUP_SEGMENT_DEPTH
    )
    for segment in segments[:searched_depth]:
        if segment in ROUTE_GROUP_BY_SEGMENT:
            return ROUTE_GROUP_BY_SEGMENT[segment]
    return "unknown"


def get_route_impl(route_group: str) -> RouteImplementation:
    """Read ``ROUTE_IMPL_<GROUP>``, defaulting to the Flask fallback.

    Raises ValueError if the variable names an unknown implementation.
    """
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
    def from_environment(cls) -> RouteImplementationSettings:
        """Read and validate each Stage 6 route selector independently."""
        return cls(
            health=get_route_impl("health"),
            specification=get_route_impl("specification"),
            metadata=get_route_impl("metadata"),
        )


def get_db_write(entity: str) -> str:
    """Read the ``DB_WRITE_<ENTITY>`` write source, defaulting to Cloud SQL.

    Raises ValueError if the variable names an unknown source.
    """
    env_name = f"DB_WRITE_{entity.upper()}"
    return _read_choice(env_name, DEFAULT_DB_SOURCE, DB_WRITE_SOURCES)


def get_db_read(entity: str) -> str:
    """Read the ``DB_READ_<ENTITY>`` read source, defaulting to Cloud SQL.

    Raises ValueError if the variable names an unknown source.
    """
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


def get_v1_household_write_source() -> str:
    """Select Cloud SQL alone or immediate copying to Supabase."""
    return _read_choice(
        "DB_WRITE_HOUSEHOLD",
        DEFAULT_DB_SOURCE,
        V1_HOUSEHOLD_WRITE_SOURCES,
    )


def get_v1_household_read_source() -> str:
    """Require every v1 household read to remain on Cloud SQL in Phase 11."""
    return _read_choice(
        "DB_READ_HOUSEHOLD",
        DEFAULT_DB_SOURCE,
        V1_HOUSEHOLD_READ_SOURCES,
    )


def get_sim_compute(flow: str) -> str:
    """Read the ``SIM_COMPUTE_<FLOW>`` compute backend, defaulting to the old gateway.

    Raises ValueError if the variable names an unknown backend.
    """
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


def _validated_explicit_sources(
    sources: ExplicitDatabaseSources,
) -> tuple[str | None, str | None]:
    """Return the explicit write and read sources, or raise ValueError if unknown."""
    db_write_source = sources.db_write_source
    if db_write_source is not None and db_write_source not in DB_WRITE_SOURCES:
        msg = f"invalid explicit database write source {db_write_source!r}"
        raise ValueError(msg)
    db_read_source = sources.db_read_source
    if db_read_source is not None and db_read_source not in DB_READ_SOURCES:
        msg = f"invalid explicit database read source {db_read_source!r}"
        raise ValueError(msg)
    return db_write_source, db_read_source


def get_migration_context(
    route_group: str,
    *,
    route_impl: RouteImplementation | None = None,
    explicit_db_sources: ExplicitDatabaseSources | None = None,
    include_compute: bool = True,
) -> MigrationContext:
    """Return current migration flag values for a request or route group.

    The route group's configuration names its database entity and simulation
    flow. ``explicit_db_sources`` replaces the configured database source flags.
    ``include_compute=False`` describes a persistence-only request in a route
    group that also computes, so it carries no simulation flow or compute
    selection.
    """
    route_config = ROUTE_GROUP_CONFIG_BY_NAME.get(route_group)
    db_entity = route_config.db_entity if route_config is not None else None
    sim_flow = (
        route_config.sim_flow if include_compute and route_config is not None else None
    )

    if explicit_db_sources is None:
        db_write = get_db_write(db_entity) if db_entity else None
        db_read = get_db_read(db_entity) if db_entity else None
    else:
        db_write, db_read = _validated_explicit_sources(explicit_db_sources)

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
    explicit_db_sources: ExplicitDatabaseSources | None = None,
    include_compute: bool = True,
) -> dict:
    """Best-effort logging context; never raises on invalid flag settings."""
    try:
        return get_migration_context(
            route_group,
            route_impl=route_impl,
            explicit_db_sources=explicit_db_sources,
            include_compute=include_compute,
        ).to_log_dict()
    except ValueError as error:
        return {
            "route_group": route_group,
            "migration_flag_error": str(error),
        }

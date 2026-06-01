"""Typed migration registry for route-group metadata."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RouteGroupConfig:
    name: str
    path_segments: tuple[str, ...]
    db_entity: str | None = None
    sim_flow: str | None = None


ROUTE_GROUPS: tuple[RouteGroupConfig, ...] = (
    RouteGroupConfig(
        name="metadata",
        path_segments=("metadata",),
        db_entity="metadata",
    ),
    RouteGroupConfig(
        name="policy",
        path_segments=("policy", "policies", "user-policy"),
        db_entity="policy",
    ),
    RouteGroupConfig(
        name="household",
        path_segments=("household", "calculate", "calculate-full"),
        db_entity="household",
        sim_flow="household",
    ),
    RouteGroupConfig(
        name="economy",
        path_segments=("economy",),
        db_entity="simulation",
        sim_flow="economy",
    ),
    RouteGroupConfig(
        name="simulation",
        path_segments=("simulation", "simulations"),
        db_entity="simulation",
        sim_flow="economy",
    ),
    RouteGroupConfig(
        name="report",
        path_segments=("report",),
        db_entity="report",
        sim_flow="report",
    ),
    RouteGroupConfig(
        name="user_profile",
        path_segments=("user-profile",),
        db_entity="user",
    ),
    RouteGroupConfig(
        name="simulation_analysis",
        path_segments=("simulation-analysis",),
    ),
    RouteGroupConfig(
        name="tracer_analysis",
        path_segments=("tracer-analysis",),
    ),
    RouteGroupConfig(
        name="ai",
        path_segments=("ai-prompts",),
    ),
)

ROUTE_GROUP_BY_SEGMENT = {
    segment: group.name for group in ROUTE_GROUPS for segment in group.path_segments
}

ROUTE_GROUP_CONFIG_BY_NAME = {group.name: group for group in ROUTE_GROUPS}

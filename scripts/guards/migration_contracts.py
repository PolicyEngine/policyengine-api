"""Guardrails for API v2 migration contract metadata."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts import export_migration_contracts

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_CURRENT_CONTRACTS = frozenset({"api_v1_compatible", "typed_v2_resources"})
# User-owned routes must never become less restrictive during a cutover: each
# contract requires a signed-in user's bearer token or a signed-out browser's
# unauthenticated-user UUID.
USER_OWNED_PATH_PREFIXES = ("/v2/me", "/v2/user-")
AUTHORIZATION_HEADER = "Authorization"
UNAUTHENTICATED_USER_HEADER = "PolicyEngine-Unauthenticated-User"
USER_CREDENTIAL_HEADERS = frozenset({AUTHORIZATION_HEADER, UNAUTHENTICATED_USER_HEADER})


def _check_unique_values(
    values: list[str],
    *,
    label: str,
) -> list[str]:
    violations = []
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    for value in sorted(duplicates):
        violations.append(f"duplicate {label}: {value!r}")
    return violations


def _check_route_groups(payload: dict[str, Any]) -> list[str]:
    violations = []
    route_groups = payload["route_groups"]
    names = [group["name"] for group in route_groups]
    violations.extend(_check_unique_values(names, label="route group"))

    route_group_by_segment: dict[str, str] = {}
    for group in route_groups:
        if not group["path_segments"]:
            violations.append(f"{group['name']}: path_segments must not be empty")
        for segment in group["path_segments"]:
            existing_group = route_group_by_segment.get(segment)
            if existing_group is not None:
                violations.append(
                    f"duplicate route path segment {segment!r} appears in "
                    f"{existing_group!r} and {group['name']!r}"
                )
                continue
            route_group_by_segment[segment] = group["name"]
        if group["db_entity"] == "":
            violations.append(f"{group['name']}: db_entity should be null, not empty")
        if group["sim_flow"] == "":
            violations.append(f"{group['name']}: sim_flow should be null, not empty")

    return violations


def _check_workflows(payload: dict[str, Any]) -> list[str]:
    violations = []
    declared_route_groups = {group["name"] for group in payload["route_groups"]}
    workflows = payload["workflows"]
    violations.extend(
        _check_unique_values(
            [workflow["name"] for workflow in workflows],
            label="workflow",
        )
    )

    request_keys = []
    for workflow in workflows:
        if workflow["current_contract"] not in ALLOWED_CURRENT_CONTRACTS:
            violations.append(f"{workflow['name']}: current_contract is not recognized")
        if not workflow["future_owner_pr"]:
            violations.append(f"{workflow['name']}: future_owner_pr is required")
        if not workflow["requests"]:
            violations.append(f"{workflow['name']}: at least one request is required")

        for request in workflow["requests"]:
            headers = request.get("headers", [])
            context = f"{workflow['name']} {request['method']} {request['path']}"
            # One route may be recorded once per credential that can call it.
            request_keys.append(
                " ".join((request["method"], request["path"], *sorted(headers)))
            )
            if request["route_group"] not in declared_route_groups:
                violations.append(
                    f"{context}: unknown route_group {request['route_group']!r}"
                )
            if (
                not request["stable_response_fields"]
                and request["expected_status"] != 204
            ):
                violations.append(f"{context}: stable_response_fields is required")
            if not request["path"].startswith("/"):
                violations.append(f"{context}: path must start with /")
            if request["path"].startswith(
                USER_OWNED_PATH_PREFIXES
            ) and USER_CREDENTIAL_HEADERS.isdisjoint(headers):
                violations.append(
                    f"{context}: user-owned routes must require the "
                    f"{AUTHORIZATION_HEADER} or {UNAUTHENTICATED_USER_HEADER} header"
                )
            if request["expected_status"] not in {200, 201, 202, 204}:
                violations.append(
                    f"{context}: unexpected status {request['expected_status']}"
                )

    violations.extend(_check_unique_values(request_keys, label="contract request"))
    return violations


def _check_generated_artifacts(payload: dict[str, Any]) -> list[str]:
    violations = []
    expected_json = export_migration_contracts.json_text(payload)
    expected_markdown = export_migration_contracts.render_markdown(payload)

    artifact_expectations = (
        (export_migration_contracts.DEFAULT_JSON, expected_json),
        (export_migration_contracts.DEFAULT_MARKDOWN, expected_markdown),
    )
    for path, expected in artifact_expectations:
        if not path.exists():
            violations.append(f"{path.relative_to(REPO_ROOT)} is missing")
            continue
        if path.read_text() != expected:
            violations.append(
                f"{path.relative_to(REPO_ROOT)} is stale; run "
                "python scripts/export_migration_contracts.py"
            )

    return violations


def check() -> list[str]:
    payload = export_migration_contracts.build_payload()
    return [
        *_check_route_groups(payload),
        *_check_workflows(payload),
        *_check_generated_artifacts(payload),
    ]


def main() -> int:
    violations = check()
    if not violations:
        print("migration-contracts guard passed")
        return 0

    print("migration-contracts guard failed:")
    for violation in violations:
        print(f"  - {violation}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

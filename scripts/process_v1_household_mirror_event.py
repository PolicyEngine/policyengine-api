#!/usr/bin/env python3
"""Copy one explicitly selected pending v1 household event into API v2."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
import os
import sys

from policyengine_api.gcp_logging import logger
from policyengine_api.services.household_mirroring import (
    process_household_event_after_commit,
)


class HouseholdEventCommandConfigurationError(RuntimeError):
    """Raised when command execution does not identify an authorized target."""


def _required(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise HouseholdEventCommandConfigurationError(f"{name} is required")
    return value


def validate_command_environment(
    selected_environment: str,
    environ: Mapping[str, str],
) -> dict[str, str]:
    """Require matching source, destination, and operator declarations."""

    deployment_environment = _required(environ, "DEPLOYMENT_ENVIRONMENT")
    supabase_environment = _required(environ, "V2_SUPABASE_ENVIRONMENT")
    if deployment_environment != selected_environment:
        raise HouseholdEventCommandConfigurationError(
            "DEPLOYMENT_ENVIRONMENT does not match --environment"
        )
    if supabase_environment != selected_environment:
        raise HouseholdEventCommandConfigurationError(
            "V2_SUPABASE_ENVIRONMENT does not match --environment"
        )

    cloud_sql_instance = _required(
        environ,
        "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME",
    )
    production_cloud_sql_instance = _required(
        environ,
        "PRODUCTION_POLICYENGINE_DB_INSTANCE_CONNECTION_NAME",
    )
    supabase_project = _required(environ, "V2_SUPABASE_PROJECT_REF")
    production_supabase_project = _required(
        environ,
        "PRODUCTION_V2_SUPABASE_PROJECT_REF",
    )
    if selected_environment == "staging":
        if cloud_sql_instance == production_cloud_sql_instance:
            raise HouseholdEventCommandConfigurationError(
                "staging Cloud SQL instance must differ from production"
            )
        if supabase_project == production_supabase_project:
            raise HouseholdEventCommandConfigurationError(
                "staging Supabase project must differ from production"
            )
    else:
        if cloud_sql_instance != production_cloud_sql_instance:
            raise HouseholdEventCommandConfigurationError(
                "production Cloud SQL instance does not match its declared identity"
            )
        if supabase_project != production_supabase_project:
            raise HouseholdEventCommandConfigurationError(
                "production Supabase project does not match its declared identity"
            )

    operator_identity = _required(environ, "HOUSEHOLD_MIRROR_OPERATOR_IDENTITY")
    allowed_operator_identity = _required(
        environ,
        "ALLOWED_HOUSEHOLD_MIRROR_OPERATOR_IDENTITY",
    )
    if operator_identity != allowed_operator_identity:
        raise HouseholdEventCommandConfigurationError(
            "declared operator identity is not authorized for household event processing"
        )
    return {
        "environment": selected_environment,
        "cloud_sql_instance": cloud_sql_instance,
        "supabase_project_ref": supabase_project,
        "operator_identity": operator_identity,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--environment",
        required=True,
        choices=("staging", "production"),
    )
    parser.add_argument("--country-id", required=True, choices=("us", "uk"))
    parser.add_argument("--legacy-household-id", required=True, type=int)
    return parser


def _record_command_outcome(
    *,
    identity: Mapping[str, str] | None,
    country_id: str,
    legacy_household_id: int,
    outcome: str,
    destination_household_id: object | None = None,
    error_type: str | None = None,
) -> None:
    """Write an audit record without source data or credentials."""

    logger.log_struct(
        {
            "message": "Explicit v1 household create-event processing completed",
            "metric_name": "v1_household_event_operator_operations",
            "metric_value": 1,
            "environment": identity.get("environment") if identity else None,
            "cloud_sql_instance": (
                identity.get("cloud_sql_instance") if identity else None
            ),
            "supabase_project_ref": (
                identity.get("supabase_project_ref") if identity else None
            ),
            "operator_identity": (
                identity.get("operator_identity") if identity else None
            ),
            "country_id": country_id,
            "legacy_household_id": legacy_household_id,
            "destination_household_id": (
                str(destination_household_id)
                if destination_household_id is not None
                else None
            ),
            "outcome": outcome,
            "error_type": error_type,
        },
        severity="INFO" if outcome == "ok" else "ERROR",
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if args.legacy_household_id < 0:
        _parser().error("--legacy-household-id must be non-negative")
    values = os.environ if environ is None else environ
    identity: dict[str, str] | None = None
    try:
        identity = validate_command_environment(args.environment, values)
        result = process_household_event_after_commit(
            args.country_id,
            args.legacy_household_id,
            require_pending=True,
        )
    except Exception as error:  # noqa: BLE001 - command emits a safe result
        try:
            _record_command_outcome(
                identity=identity,
                country_id=args.country_id,
                legacy_household_id=args.legacy_household_id,
                outcome="error",
                error_type=type(error).__name__,
            )
        except Exception:
            pass
        safe_types = (HouseholdEventCommandConfigurationError,)
        message = (
            str(error)
            if isinstance(error, safe_types)
            else "household create-event processing failed"
        )
        print(
            json.dumps(
                {
                    "outcome": "error",
                    "country_id": args.country_id,
                    "legacy_household_id": args.legacy_household_id,
                    "error": {"type": type(error).__name__, "message": message},
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    try:
        _record_command_outcome(
            identity=identity,
            country_id=args.country_id,
            legacy_household_id=args.legacy_household_id,
            outcome="ok",
            destination_household_id=result.household_id,
        )
    except Exception:
        pass
    print(
        json.dumps(
            {
                "outcome": "ok",
                "environment": identity["environment"],
                "country_id": args.country_id,
                "legacy_household_id": args.legacy_household_id,
                "destination_household_id": str(result.household_id),
                "household_created": result.household_created,
                "mapping_created": result.mapping_created,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Tests for exact v1 household create-event processing command."""

from __future__ import annotations

from unittest.mock import Mock
from uuid import UUID

import pytest
from sqlalchemy import Engine

from policyengine_api.services.v2.households.types import (
    LegacyHouseholdPersistenceResult,
)
from scripts import process_v1_household_mirror_event as command


STAGING_ENVIRONMENT = {
    "DEPLOYMENT_ENVIRONMENT": "staging",
    "V2_SUPABASE_ENVIRONMENT": "staging",
    "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": "project:region:staging-db",
    "PRODUCTION_POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": (
        "project:region:production-db"
    ),
    "V2_SUPABASE_PROJECT_REF": "abcdefghijklmnopqrst",
    "PRODUCTION_V2_SUPABASE_PROJECT_REF": "zyxwvutsrqponmlkjihg",
    "HOUSEHOLD_MIRROR_OPERATOR_IDENTITY": "stage11-operator@example.iam",
    "ALLOWED_HOUSEHOLD_MIRROR_OPERATOR_IDENTITY": "stage11-operator@example.iam",
}


def test_environment_validation_requires_distinct_staging_targets_and_operator() -> (
    None
):
    identity = command.validate_command_environment(
        "staging",
        STAGING_ENVIRONMENT,
    )
    assert identity["environment"] == "staging"

    conflicts = [
        {"DEPLOYMENT_ENVIRONMENT": "production"},
        {"V2_SUPABASE_ENVIRONMENT": "production"},
        {
            "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": (
                STAGING_ENVIRONMENT[
                    "PRODUCTION_POLICYENGINE_DB_INSTANCE_CONNECTION_NAME"
                ]
            )
        },
        {
            "V2_SUPABASE_PROJECT_REF": STAGING_ENVIRONMENT[
                "PRODUCTION_V2_SUPABASE_PROJECT_REF"
            ]
        },
        {"HOUSEHOLD_MIRROR_OPERATOR_IDENTITY": "unapproved@example.iam"},
    ]
    for conflict in conflicts:
        with pytest.raises(command.HouseholdEventCommandConfigurationError):
            command.validate_command_environment(
                "staging",
                {**STAGING_ENVIRONMENT, **conflict},
            )


def test_production_validation_requires_exact_declared_targets() -> None:
    production = {
        **STAGING_ENVIRONMENT,
        "DEPLOYMENT_ENVIRONMENT": "production",
        "V2_SUPABASE_ENVIRONMENT": "production",
        "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME": (
            STAGING_ENVIRONMENT["PRODUCTION_POLICYENGINE_DB_INSTANCE_CONNECTION_NAME"]
        ),
        "V2_SUPABASE_PROJECT_REF": STAGING_ENVIRONMENT[
            "PRODUCTION_V2_SUPABASE_PROJECT_REF"
        ],
    }

    assert (
        command.validate_command_environment("production", production)["environment"]
        == "production"
    )


def test_command_processes_one_explicit_pending_event_and_records_success(
    monkeypatch,
    capsys,
) -> None:
    destination_id = UUID("00000000-0000-0000-0000-000000000010")
    process = Mock(
        return_value=LegacyHouseholdPersistenceResult(
            household_id=destination_id,
            household_created=True,
            mapping_created=True,
        )
    )
    audit = Mock()
    monkeypatch.setattr(command, "process_household_event_after_commit", process)
    monkeypatch.setattr(command.logger, "log_struct", audit)

    status = command.main(
        [
            "--environment",
            "staging",
            "--country-id",
            "us",
            "--legacy-household-id",
            "42",
        ],
        environ=STAGING_ENVIRONMENT,
    )

    assert status == 0
    process.assert_called_once_with("us", 42, require_pending=True)
    assert '"destination_household_id": "00000000-0000-0000-0000-000000000010"' in (
        capsys.readouterr().out
    )
    audit.assert_called_once()
    audit_fields = audit.call_args.args[0]
    assert audit_fields["operator_identity"] == "stage11-operator@example.iam"
    assert audit_fields["outcome"] == "ok"


def test_command_uses_selected_cloud_sql_proxy(monkeypatch, capsys) -> None:
    destination_id = UUID("00000000-0000-0000-0000-000000000011")
    process = Mock(
        return_value=LegacyHouseholdPersistenceResult(
            household_id=destination_id,
            household_created=False,
            mapping_created=True,
        )
    )
    engine = Mock(spec=Engine)
    event_service = Mock()
    monkeypatch.setattr(command, "process_household_event_after_commit", process)
    monkeypatch.setattr(command.logger, "log_struct", Mock())
    monkeypatch.setattr(
        command,
        "_proxy_event_service",
        Mock(return_value=(event_service, engine)),
    )

    status = command.main(
        [
            "--environment",
            "staging",
            "--country-id",
            "us",
            "--legacy-household-id",
            "43",
        ],
        environ={**STAGING_ENVIRONMENT, "POLICYENGINE_DB_PROXY_PORT": "3307"},
    )

    assert status == 0, capsys.readouterr().err
    process.assert_called_once_with(
        "us",
        43,
        event_service=event_service,
        require_pending=True,
    )
    engine.dispose.assert_called_once_with()


def test_command_redacts_processing_failure_and_records_error(
    monkeypatch,
    capsys,
) -> None:
    audit = Mock()
    monkeypatch.setattr(
        command,
        "process_household_event_after_commit",
        Mock(
            side_effect=RuntimeError("postgresql://user:secret@private-host/database")
        ),
    )
    monkeypatch.setattr(command.logger, "log_struct", audit)

    status = command.main(
        [
            "--environment",
            "staging",
            "--country-id",
            "uk",
            "--legacy-household-id",
            "51",
        ],
        environ=STAGING_ENVIRONMENT,
    )

    assert status == 1
    error_output = capsys.readouterr().err
    assert "create-event processing failed" in error_output
    assert "secret" not in error_output
    assert "private-host" not in error_output
    assert audit.call_args.args[0]["outcome"] == "error"

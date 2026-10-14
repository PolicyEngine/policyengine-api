"""Tests for exact v1 household create-event processing command."""

from __future__ import annotations

from unittest.mock import Mock
from uuid import UUID

import pytest
from sqlalchemy import Engine
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from policyengine_api.services.v2.households.types import (
    LegacyHouseholdPersistenceResult,
)
from scripts import process_v1_household_mirror_event as command

PROXY_PASSWORD = "proxy-password"
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


def _staging_identity_fields() -> dict[str, str]:
    return {
        "environment": "staging",
        "cloud_sql_instance": "project:region:staging-db",
        "supabase_project_ref": "abcdefghijklmnopqrst",
        "operator_identity": "stage11-operator@example.iam",
    }


def _run_staging_command(environ, legacy_household_id="42") -> int:
    return command.main(
        [
            "--environment",
            "staging",
            "--country-id",
            "us",
            "--legacy-household-id",
            legacy_household_id,
        ],
        environ=environ,
    )


def test_success_audit_record_lists_every_field(monkeypatch, capsys) -> None:
    destination_id = UUID("00000000-0000-0000-0000-000000000012")
    monkeypatch.setattr(
        command,
        "process_household_event_after_commit",
        Mock(
            return_value=LegacyHouseholdPersistenceResult(
                household_id=destination_id,
                household_created=True,
                mapping_created=False,
            )
        ),
    )
    audit = Mock()
    monkeypatch.setattr(command.logger, "log_struct", audit)

    assert _run_staging_command(STAGING_ENVIRONMENT) == 0

    audit.assert_called_once_with(
        {
            "message": "Explicit v1 household create-event processing completed",
            "metric_name": "v1_household_event_operator_operations",
            "metric_value": 1,
            **_staging_identity_fields(),
            "country_id": "us",
            "legacy_household_id": 42,
            "destination_household_id": str(destination_id),
            "outcome": "ok",
            "error_type": None,
        },
        severity="INFO",
    )
    assert capsys.readouterr().out == (
        '{"country_id": "us", "destination_household_id": '
        '"00000000-0000-0000-0000-000000000012", "environment": "staging", '
        '"household_created": true, "legacy_household_id": 42, '
        '"mapping_created": false, "outcome": "ok"}\n'
    )


def test_failure_audit_record_names_only_the_error_type(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        command,
        "process_household_event_after_commit",
        Mock(side_effect=LookupError("secret detail")),
    )
    audit = Mock()
    monkeypatch.setattr(command.logger, "log_struct", audit)

    assert _run_staging_command(STAGING_ENVIRONMENT) == 1

    audit.assert_called_once_with(
        {
            "message": "Explicit v1 household create-event processing completed",
            "metric_name": "v1_household_event_operator_operations",
            "metric_value": 1,
            **_staging_identity_fields(),
            "country_id": "us",
            "legacy_household_id": 42,
            "destination_household_id": None,
            "outcome": "error",
            "error_type": "LookupError",
        },
        severity="ERROR",
    )
    assert capsys.readouterr().err == (
        '{"country_id": "us", "error": {"message": "household create-event '
        'processing failed", "type": "LookupError"}, "legacy_household_id": 42, '
        '"outcome": "error"}\n'
    )


def test_configuration_failure_audit_record_has_no_identity(
    monkeypatch, capsys
) -> None:
    audit = Mock()
    monkeypatch.setattr(command.logger, "log_struct", audit)
    environ = {**STAGING_ENVIRONMENT, "DEPLOYMENT_ENVIRONMENT": ""}

    assert _run_staging_command(environ, legacy_household_id="7") == 1

    audit.assert_called_once_with(
        {
            "message": "Explicit v1 household create-event processing completed",
            "metric_name": "v1_household_event_operator_operations",
            "metric_value": 1,
            "environment": None,
            "cloud_sql_instance": None,
            "supabase_project_ref": None,
            "operator_identity": None,
            "country_id": "us",
            "legacy_household_id": 7,
            "destination_household_id": None,
            "outcome": "error",
            "error_type": "HouseholdEventCommandConfigurationError",
        },
        severity="ERROR",
    )
    assert capsys.readouterr().err == (
        '{"country_id": "us", "error": {"message": "DEPLOYMENT_ENVIRONMENT is '
        'required", "type": "HouseholdEventCommandConfigurationError"}, '
        '"legacy_household_id": 7, "outcome": "error"}\n'
    )


def test_audit_failure_does_not_change_the_command_result(monkeypatch) -> None:
    monkeypatch.setattr(
        command,
        "process_household_event_after_commit",
        Mock(
            return_value=LegacyHouseholdPersistenceResult(
                household_id=UUID("00000000-0000-0000-0000-000000000013"),
                household_created=True,
                mapping_created=True,
            )
        ),
    )
    monkeypatch.setattr(
        command.logger, "log_struct", Mock(side_effect=RuntimeError("log down"))
    )

    assert _run_staging_command(STAGING_ENVIRONMENT) == 0


@pytest.mark.parametrize("raw_port", ["", "   "])
def test_proxy_is_not_used_without_a_port(raw_port) -> None:
    assert command._proxy_event_service({"POLICYENGINE_DB_PROXY_PORT": raw_port}) == (
        None,
        None,
    )
    assert command._proxy_event_service({}) == (None, None)


@pytest.mark.parametrize(
    ("raw_port", "message"),
    [
        ("proxy", "POLICYENGINE_DB_PROXY_PORT must be an integer"),
        ("0", "POLICYENGINE_DB_PROXY_PORT is outside the valid range"),
        ("65536", "POLICYENGINE_DB_PROXY_PORT is outside the valid range"),
        ("-1", "POLICYENGINE_DB_PROXY_PORT is outside the valid range"),
    ],
)
def test_proxy_port_must_be_a_valid_tcp_port(raw_port, message) -> None:
    with pytest.raises(
        command.HouseholdEventCommandConfigurationError, match=f"^{message}$"
    ):
        command._proxy_event_service(
            {
                "POLICYENGINE_DB_PROXY_PORT": raw_port,
                "POLICYENGINE_DB_PASSWORD": PROXY_PASSWORD,
            }
        )


@pytest.mark.parametrize(("raw_port", "port"), [("1", 1), (" 65535 ", 65535)])
def test_proxy_connects_as_the_migration_user(monkeypatch, raw_port, port) -> None:
    engine = Mock(spec=Engine)
    create_engine = Mock(return_value=engine)
    session_factory = Mock()
    build_session_factory = Mock(return_value=session_factory)
    household_service = Mock()
    monkeypatch.setattr(command, "create_engine", create_engine)
    monkeypatch.setattr(command, "build_session_factory", build_session_factory)
    monkeypatch.setattr(command, "HouseholdService", household_service)

    service, returned_engine = command._proxy_event_service(
        {
            "POLICYENGINE_DB_PROXY_PORT": raw_port,
            "POLICYENGINE_DB_PASSWORD": PROXY_PASSWORD,
        }
    )

    assert returned_engine is engine
    assert service is household_service.return_value
    household_service.assert_called_once_with(session_factory)
    build_session_factory.assert_called_once_with(engine)
    create_engine.assert_called_once_with(
        URL.create(
            "mysql+pymysql",
            username="policyengine_schema_migrator",
            password=PROXY_PASSWORD,
            host="127.0.0.1",
            port=port,
            database="policyengine",
        ),
        poolclass=NullPool,
    )


def test_proxy_requires_the_database_password() -> None:
    with pytest.raises(
        command.HouseholdEventCommandConfigurationError,
        match=r"^POLICYENGINE_DB_PASSWORD is required$",
    ):
        command._proxy_event_service({"POLICYENGINE_DB_PROXY_PORT": "3307"})

"""Guards on the v1 models' schema, read through their mappers.

The tables are read through each mapped class's mapper, and their MySQL DDL is
rendered by creating the schema on SQLAlchemy's mock engine, which compiles the
statements and connects to no database.
"""

import re

from sqlalchemy import create_mock_engine, inspect

from policyengine_api.data.v1_models import (
    ComputedHousehold,
    LegacyReportOutputAlias,
    Policy,
    UserPolicy,
    UserPolicyMirrorEvent,
    UserProfile,
    V1Base,
)

EXPECTED_TABLES = {
    "analysis",
    "computed_household",
    "economy",
    "household",
    "household_mirror_events",
    "legacy_report_output_aliases",
    "policy",
    "reform_impact",
    "report_output_runs",
    "report_outputs",
    "simulation_runs",
    "simulations",
    "user_policies",
    "user_policy_mirror_events",
    "user_profiles",
}


def _mapped_table_names() -> set[str]:
    return {mapper.class_.__tablename__ for mapper in V1Base.registry.mappers}


def _mysql_create_table_statements() -> dict[str, str]:
    """Return each v1 table's CREATE TABLE statement compiled for MySQL."""
    statements: dict[str, str] = {}

    def record(ddl: object, *_parameters: object, **_options: object) -> None:
        compiled = str(ddl.compile(dialect=ddl_recorder.dialect))
        if match := re.match(r"\s*CREATE TABLE (\w+)", compiled):
            statements[match.group(1)] = compiled

    ddl_recorder = create_mock_engine("mysql://", record)
    V1Base.metadata.create_all(ddl_recorder, checkfirst=False)
    return statements


def test_v1_metadata_contains_every_legacy_table():
    assert _mapped_table_names() == EXPECTED_TABLES


def test_tracer_table_is_absent_after_sqlite_cache_removal():
    assert "tracers" not in _mapped_table_names()


def test_v1_metadata_compiles_for_the_production_mysql_dialect():
    statements = _mysql_create_table_statements()

    assert set(statements) == EXPECTED_TABLES
    assert all(statements.values())


def test_v1_composite_and_unique_keys_match_legacy_contract():
    policy = inspect(Policy)
    assert policy.columns["id"].autoincrement is True
    assert [column.name for column in policy.primary_key] == [
        "id",
        "country_id",
        "policy_hash",
    ]
    computed = inspect(ComputedHousehold)
    assert [column.name for column in computed.primary_key] == [
        "household_id",
        "policy_id",
        "country_id",
    ]
    assert inspect(UserProfile).columns["auth0_id"].unique
    assert inspect(UserPolicy).columns["mirror_revision"].default.arg == 0
    assert inspect(UserPolicyMirrorEvent).columns["id"].autoincrement is True
    mirror_events_table = _mysql_create_table_statements()["user_policy_mirror_events"]
    assert re.findall(r"UNIQUE \(([^)]*)\)", mirror_events_table) == [
        "country_id, legacy_user_policy_id, source_revision"
    ]
    assert (
        inspect(LegacyReportOutputAlias)
        .columns["legacy_report_output_id"]
        .autoincrement
        is False
    )

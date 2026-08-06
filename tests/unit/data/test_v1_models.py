from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from policyengine_api.data.v1_models import V1Base


EXPECTED_TABLES = {
    "analysis",
    "computed_household",
    "economy",
    "household",
    "legacy_report_output_aliases",
    "policy",
    "reform_impact",
    "report_output_runs",
    "report_outputs",
    "simulation_runs",
    "simulations",
    "tracers",
    "user_policies",
    "user_profiles",
}


def test_v1_metadata_contains_every_legacy_table():
    assert set(V1Base.metadata.tables) == EXPECTED_TABLES


def test_v1_metadata_compiles_for_the_production_mysql_dialect():
    for table in V1Base.metadata.sorted_tables:
        assert str(CreateTable(table).compile(dialect=mysql.dialect()))


def test_v1_composite_and_unique_keys_match_legacy_contract():
    policy = V1Base.metadata.tables["policy"]
    assert policy.c.id.autoincrement is True
    assert [column.name for column in policy.primary_key.columns] == [
        "id",
        "country_id",
        "policy_hash",
    ]
    computed = V1Base.metadata.tables["computed_household"]
    assert [column.name for column in computed.primary_key.columns] == [
        "household_id",
        "policy_id",
        "country_id",
    ]
    assert V1Base.metadata.tables["user_profiles"].c.auth0_id.unique
    assert (
        V1Base.metadata.tables[
            "legacy_report_output_aliases"
        ].c.legacy_report_output_id.autoincrement
        is False
    )

from sqlalchemy import create_engine

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


def test_v1_metadata_builds_a_fresh_sqlite_database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    V1Base.metadata.create_all(engine)

    with engine.connect() as connection:
        table_names = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert EXPECTED_TABLES <= table_names


def test_v1_composite_and_unique_keys_match_legacy_contract():
    policy = V1Base.metadata.tables["policy"]
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

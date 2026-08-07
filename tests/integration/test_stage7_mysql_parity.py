"""Behavioral parity between legacy SQL and typed DAO access on MySQL."""

import json
from datetime import datetime

from alembic import command
from sqlalchemy import text

from policyengine_api.data.orm import SessionManager
from policyengine_api.data.v1_daos import V1UnitOfWork
from policyengine_api.services.reform_impacts_service import ReformImpactsService
from tests.integration.stage7_mysql import alembic_config


def test_typed_daos_preserve_legacy_mapping_shapes(stage7_mysql):
    database_url, engine = stage7_mysql
    command.upgrade(alembic_config(database_url), "head")
    unit_of_work = V1UnitOfWork(SessionManager(engine))

    with unit_of_work.transaction() as repositories:
        policy_id = repositories.policies.create("us", None, {"x": 1}, "parity", "v1")
        household_id = repositories.households.create(
            "us", None, {"people": {}}, "household-parity", "v1"
        )
        user_id = repositories.users.create_profile(
            "auth0|parity", None, "us", 123456789
        )

    with engine.connect() as connection:
        legacy_policy = dict(
            connection.execute(
                text(
                    "SELECT * FROM policy "
                    "WHERE id = :policy_id AND country_id = :country_id"
                ),
                {"policy_id": policy_id, "country_id": "us"},
            )
            .mappings()
            .one()
        )
        legacy_household = dict(
            connection.execute(
                text(
                    "SELECT * FROM household "
                    "WHERE id = :household_id AND country_id = :country_id"
                ),
                {"household_id": household_id, "country_id": "us"},
            )
            .mappings()
            .one()
        )
        legacy_user = dict(
            connection.execute(
                text("SELECT * FROM user_profiles WHERE user_id = :user_id"),
                {"user_id": user_id},
            )
            .mappings()
            .one()
        )

    legacy_policy["policy_json"] = json.loads(legacy_policy["policy_json"])
    legacy_household["household_json"] = json.loads(legacy_household["household_json"])
    with unit_of_work.read() as repositories:
        assert legacy_policy == repositories.policies.get("us", policy_id)
        assert legacy_household == repositories.households.get("us", household_id)
        assert legacy_user == repositories.users.get_profile(user_id=user_id)


def test_typed_daos_read_rows_written_by_legacy_sql(stage7_mysql):
    database_url, engine = stage7_mysql
    command.upgrade(alembic_config(database_url), "head")
    unit_of_work = V1UnitOfWork(SessionManager(engine))
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO household "
                "(country_id, label, api_version, household_json, household_hash) "
                "VALUES (:country_id, :label, :api_version, :household_json, "
                ":household_hash)"
            ),
            {
                "country_id": "us",
                "label": "legacy",
                "api_version": "v1",
                "household_json": '{"legacy": true}',
                "household_hash": "legacy-row",
            },
        )
        row = (
            connection.execute(
                text("SELECT * FROM household WHERE household_hash = :household_hash"),
                {"household_hash": "legacy-row"},
            )
            .mappings()
            .one()
        )

    legacy_shape = dict(row)
    legacy_shape["household_json"] = json.loads(legacy_shape["household_json"])
    with unit_of_work.read() as repositories:
        assert repositories.households.get("us", row["id"]) == legacy_shape


def test_reform_impact_service_stores_mysql_json_objects(stage7_mysql):
    database_url, engine = stage7_mysql
    command.upgrade(alembic_config(database_url), "head")
    unit_of_work = V1UnitOfWork(SessionManager(engine))
    service = ReformImpactsService(unit_of_work=unit_of_work)

    service.set_reform_impact(
        country_id="us",
        policy_id=2,
        baseline_policy_id=1,
        region="us",
        dataset="default",
        time_period="2026",
        options={"scope": "test"},
        options_hash="native-json",
        status="computing",
        api_version="v1",
        reform_impact_json={},
        start_time=datetime(2026, 1, 1),
        execution_id="native-json-job",
    )
    service.set_complete_reform_impact(
        country_id="us",
        reform_policy_id=2,
        baseline_policy_id=1,
        region="us",
        dataset="default",
        time_period="2026",
        options_hash="native-json",
        reform_impact_json={"result": {"value": 1}},
        execution_id="native-json-job",
    )

    with engine.connect() as connection:
        json_types = connection.execute(
            text(
                "SELECT JSON_TYPE(options_json), JSON_TYPE(reform_impact_json) "
                "FROM reform_impact WHERE execution_id = :execution_id"
            ),
            {"execution_id": "native-json-job"},
        ).one()
    assert tuple(json_types) == ("OBJECT", "OBJECT")

    stored = service.get_all_reform_impacts(
        "us",
        2,
        1,
        "us",
        "default",
        "2026",
        "native-json",
        "v1",
    )[0]
    assert stored["options_json"] == {"scope": "test"}
    assert stored["reform_impact_json"] == {"result": {"value": 1}}

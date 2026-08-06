"""Route, Cloud SQL connector, and startup behavior on disposable MySQL."""

import importlib
import json
import os

from alembic import command
from flask import Flask
import pymysql
from sqlalchemy import text

from policyengine_api.data.orm import SessionManager
from policyengine_api.data.v1_daos import V1UnitOfWork
from policyengine_api.services.household_service import HouseholdService
from policyengine_api.services.policy_service import PolicyService
from policyengine_api.services.user_service import UserService
from tests.integration.stage7_mysql import alembic_config, schema_signature


def test_public_policy_household_and_user_routes_use_mysql(stage7_mysql, monkeypatch):
    database_url, engine = stage7_mysql
    command.upgrade(alembic_config(database_url), "head")
    sessions = SessionManager(engine)
    unit_of_work = V1UnitOfWork(sessions)

    monkeypatch.setenv("FLASK_DEBUG", "1")
    from policyengine_api.routes import household_routes, policy_routes
    from policyengine_api.routes import user_profile_routes

    monkeypatch.setattr(
        policy_routes,
        "policy_service",
        PolicyService(unit_of_work=unit_of_work),
    )
    monkeypatch.setattr(
        household_routes,
        "household_service",
        HouseholdService(unit_of_work=unit_of_work),
    )
    monkeypatch.setattr(
        user_profile_routes,
        "user_service",
        UserService(unit_of_work=unit_of_work),
    )
    app = Flask(__name__)
    app.register_blueprint(policy_routes.policy_bp)
    app.register_blueprint(household_routes.household_bp)
    app.register_blueprint(user_profile_routes.user_profile_bp)
    client = app.test_client()

    policy = client.post("/us/policy", json={"label": "Route", "data": {}})
    assert policy.status_code == 201
    policy_id = policy.get_json()["result"]["policy_id"]
    policy_result = json.loads(client.get(f"/us/policy/{policy_id}").data)["result"]
    assert policy_result["id"] == policy_id

    household = client.post(
        "/us/household", json={"label": "Route", "data": {"people": {}}}
    )
    assert household.status_code == 201
    household_id = household.get_json()["result"]["household_id"]
    assert (
        client.get(f"/us/household/{household_id}").get_json()["result"]["id"]
        == household_id
    )

    user = client.post(
        "/us/user-profile",
        json={"auth0_id": "auth0|route", "username": None, "user_since": 1},
    )
    assert user.status_code == 201
    user_id = user.get_json()["result"]["user_id"]
    assert client.get(f"/us/user-profile?user_id={user_id}").status_code == 200


def test_cloud_sql_connector_pool_drives_daos_and_startup_emits_no_ddl(
    stage7_mysql, monkeypatch
):
    database_url, engine = stage7_mysql
    command.upgrade(alembic_config(database_url), "head")

    os.environ.setdefault("FLASK_DEBUG", "1")
    from policyengine_api.data import data as data_module

    url = engine.url
    connector_calls = []

    class LocalConnector:
        def __init__(self, **_kwargs):
            pass

        def connect(self, **kwargs):
            connector_calls.append(kwargs)
            return pymysql.connect(
                host=url.host,
                port=url.port,
                user=url.username,
                password=url.password,
                database=url.database,
            )

        def close(self):
            pass

    monkeypatch.setattr(data_module, "Connector", LocalConnector)
    monkeypatch.setenv("POLICYENGINE_DB_INSTANCE_CONNECTION_NAME", "toy:local:stage7")
    monkeypatch.setenv("POLICYENGINE_DB_USER", str(url.username))
    monkeypatch.setenv("POLICYENGINE_DB_NAME", str(url.database))
    monkeypatch.setenv("POLICYENGINE_DB_PASSWORD", str(url.password))

    remote_database = data_module.PolicyEngineDatabase(local=False, initialize=False)
    assert connector_calls == []
    with remote_database.pool.connect() as first:
        with remote_database.pool.connect() as second:
            first_id = first.scalar(text("SELECT CONNECTION_ID()"))
            second_id = second.scalar(text("SELECT CONNECTION_ID()"))
            assert first_id != second_id
    assert len(connector_calls) == 2

    unit_of_work = V1UnitOfWork(SessionManager(remote_database.pool))
    with unit_of_work.transaction() as repositories:
        policy_id = repositories.policies.create(
            "us", "Connector", {}, "connector-path", "v1"
        )
    with unit_of_work.read() as repositories:
        assert repositories.policies.get("us", policy_id)["label"] == "Connector"
    assert connector_calls[0]["instance_connection_string"] == "toy:local:stage7"

    monkeypatch.setattr(data_module, "database", remote_database)
    before_startup = schema_signature(engine)
    api_module = importlib.import_module("policyengine_api.api")
    importlib.reload(api_module)
    assert api_module.app.test_client().get("/liveness-check").status_code == 200
    assert schema_signature(engine) == before_startup
    remote_database._close_pool()

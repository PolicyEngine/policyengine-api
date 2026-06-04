import os

os.environ.setdefault("FLASK_DEBUG", "1")

from policyengine_api.data.data import get_remote_database_config


def test_remote_database_config_defaults_to_current_production_values(monkeypatch):
    monkeypatch.delenv("POLICYENGINE_DB_INSTANCE_CONNECTION_NAME", raising=False)
    monkeypatch.delenv("POLICYENGINE_DB_USER", raising=False)
    monkeypatch.delenv("POLICYENGINE_DB_NAME", raising=False)

    assert get_remote_database_config() == {
        "instance_connection_name": "policyengine-api:us-central1:policyengine-api-data",
        "db_user": "policyengine",
        "db_name": "policyengine",
    }


def test_remote_database_config_can_target_non_production_db(monkeypatch):
    monkeypatch.setenv(
        "POLICYENGINE_DB_INSTANCE_CONNECTION_NAME",
        "policyengine-api-staging:us-central1:policyengine-api-data-staging",
    )
    monkeypatch.setenv("POLICYENGINE_DB_USER", "policyengine_staging")
    monkeypatch.setenv("POLICYENGINE_DB_NAME", "policyengine_staging")

    assert get_remote_database_config() == {
        "instance_connection_name": (
            "policyengine-api-staging:us-central1:policyengine-api-data-staging"
        ),
        "db_user": "policyengine_staging",
        "db_name": "policyengine_staging",
    }

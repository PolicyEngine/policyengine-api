"""A new v1 policy may set only parameters that the running country model defines.

Re-saving a policy identical to a stored one returns the stored policy, whatever
its parameter paths, so policies that use since-removed parameters still resolve.
"""

from __future__ import annotations

import pytest
from flask import Flask
from sqlalchemy import select

from policyengine_api.data.v1_models import Policy
from policyengine_api.routes.policy_routes import policy_bp
from policyengine_api.utils import hash_object
from tests.fixtures.policy_parameter_paths import (
    NON_PARAMETER_CASES,
    NON_PARAMETER_PATHS,
    SETTABLE_PARAMETER_PATHS,
    policy_data,
)


@pytest.fixture(autouse=True)
def cloud_sql_only_writes(monkeypatch):
    monkeypatch.setenv("DB_WRITE_POLICY", "cloud_sql")


def _policy_client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(policy_bp)
    return app.test_client()


def _stored_policies(orm_session_factory) -> list[Policy]:
    with orm_session_factory() as session:
        return list(session.scalars(select(Policy)))


def _assert_rejected_paths(response, country_id: str, rejected_paths: list[str]):
    assert response.status_code == 400
    assert response.mimetype == "application/json"
    body = response.get_json()
    assert body["status"] == "error"
    assert body["result"] is None
    for rejected_path in rejected_paths:
        assert rejected_path in body["message"]
    assert body["errors"] == [
        {
            "type": "policy_parameter",
            "name": rejected_path,
            "path": f"data.{rejected_path}",
            "message": (
                f"Unrecognized policy parameter `{rejected_path}` at "
                f"`data.{rejected_path}`."
            ),
        }
        for rejected_path in rejected_paths
    ]
    assert f"policyengine-{country_id}" in body["message"]


@pytest.mark.parametrize(("country_id", "non_parameter_path"), NON_PARAMETER_CASES)
def test_new_policy_naming_a_path_that_is_not_a_parameter_returns_400(
    orm_session_factory,
    country_id,
    non_parameter_path,
):
    response = _policy_client().post(
        f"/{country_id}/policy",
        json={"label": "Rejected", "data": policy_data(non_parameter_path)},
    )

    _assert_rejected_paths(response, country_id, [non_parameter_path])
    assert _stored_policies(orm_session_factory) == []


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_new_policy_400_lists_every_path_that_is_not_a_parameter(
    orm_session_factory,
    country_id,
):
    non_parameter_paths = list(NON_PARAMETER_PATHS[country_id].values())
    settable_path = SETTABLE_PARAMETER_PATHS[country_id][0]
    requested_policy = policy_data(
        non_parameter_paths[0],
        settable_path,
        *non_parameter_paths[1:],
    )

    response = _policy_client().post(
        f"/{country_id}/policy",
        json={"label": "Several rejected paths", "data": requested_policy},
    )

    _assert_rejected_paths(response, country_id, sorted(non_parameter_paths))
    assert settable_path not in response.get_json()["message"]
    assert _stored_policies(orm_session_factory) == []


@pytest.mark.parametrize("country_id", ["us", "uk"])
def test_new_policy_setting_bracket_and_contributed_parameters_is_created(
    orm_session_factory,
    country_id,
):
    requested_policy = policy_data(*SETTABLE_PARAMETER_PATHS[country_id])

    response = _policy_client().post(
        f"/{country_id}/policy",
        json={"label": "Settable parameters", "data": requested_policy},
    )

    assert response.status_code == 201
    stored_policies = _stored_policies(orm_session_factory)
    assert [policy.id for policy in stored_policies] == [
        response.get_json()["result"]["policy_id"]
    ]
    assert stored_policies[0].policy_json == requested_policy


@pytest.mark.parametrize("label", ["Montana HB1", None])
def test_resaving_a_stored_policy_with_removed_parameters_returns_it(
    orm_session_factory,
    label,
):
    requested_policy = policy_data(
        NON_PARAMETER_PATHS["us"]["missing contributed parameter"],
        NON_PARAMETER_PATHS["us"]["parameter group"],
    )
    with orm_session_factory.begin() as session:
        session.add(
            Policy(
                id=98768,
                country_id="us",
                label=label,
                api_version="2.0.0",
                policy_json=requested_policy,
                policy_hash=hash_object(requested_policy),
            )
        )

    response = _policy_client().post(
        "/us/policy",
        json={"label": label, "data": requested_policy},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "message": "Policy already exists",
        "result": {"policy_id": 98768},
    }
    assert [policy.id for policy in _stored_policies(orm_session_factory)] == [98768]

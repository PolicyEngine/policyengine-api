"""Regression tests for issue #3445.

update_user_policy (policy.py) previously interpolated untrusted
payload keys directly into an UPDATE statement, allowing arbitrary
SQL fragments (and identity-column tampering) via the JSON body.

The fix rejects unknown keys with a 400 response and restricts
writable columns to a static whitelist.
"""

import time

from flask import Flask

from policyengine_api.data.v1_models import UserPolicy
from policyengine_api.routes.policy_routes import policy_bp


def _create_test_client() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(policy_bp)
    return app.test_client()


def _insert_user_policy(orm_session, *, country_id: str = "us") -> int:
    now = int(time.time())
    policy = UserPolicy(
        country_id=country_id,
        reform_label="old label",
        reform_id=2,
        baseline_label=None,
        baseline_id=1,
        user_id="user1",
        year="2025",
        geography="us",
        dataset="custom_dataset",
        number_of_provisions=3,
        api_version="1.0.0",
        added_date=now,
        updated_date=now,
    )
    orm_session.add(policy)
    orm_session.commit()
    return policy.id


def test_update_user_policy_rejects_sql_injection_key(orm_session):
    """Unknown keys (including SQL injection attempts) must be rejected."""
    policy_id = _insert_user_policy(orm_session)

    client = _create_test_client()
    response = client.put(
        "/us/user-policy",
        json={
            "id": policy_id,
            "username; DROP TABLE x --": "x",
        },
    )

    assert response.status_code == 400
    body = response.get_json()
    assert "unsupported fields" in body["message"]

    # The row must be untouched.
    orm_session.expire_all()
    assert orm_session.get(UserPolicy, policy_id).reform_label == "old label"


def test_update_user_policy_rejects_identity_column(orm_session):
    """Identity columns (user_id, country_id, ...) must not be writable."""
    policy_id = _insert_user_policy(orm_session)

    client = _create_test_client()
    response = client.put(
        "/us/user-policy",
        json={"id": policy_id, "user_id": "attacker"},
    )

    assert response.status_code == 400
    orm_session.expire_all()
    assert orm_session.get(UserPolicy, policy_id).user_id == "user1"


def test_update_user_policy_allows_whitelisted_field(orm_session):
    """Whitelisted fields (e.g. reform_label) can still be updated."""
    policy_id = _insert_user_policy(orm_session)

    client = _create_test_client()
    response = client.put(
        "/us/user-policy",
        json={"id": policy_id, "reform_label": "new label"},
    )

    assert response.status_code == 200
    orm_session.expire_all()
    assert orm_session.get(UserPolicy, policy_id).reform_label == "new label"


def test_update_user_policy_requires_id():
    client = _create_test_client()
    response = client.put("/us/user-policy", json={"reform_label": "x"})
    assert response.status_code == 400


def test_update_user_policy_requires_at_least_one_field(orm_session):
    policy_id = _insert_user_policy(orm_session)
    client = _create_test_client()
    response = client.put("/us/user-policy", json={"id": policy_id})
    assert response.status_code == 400


def test_update_user_policy_returns_not_found_for_missing_id():
    response = _create_test_client().put(
        "/us/user-policy",
        json={"id": 999_999, "reform_label": "missing"},
    )

    assert response.status_code == 404
    assert response.get_json()["message"] == "User policy #999999 not found."


def test_update_user_policy_does_not_update_another_country(orm_session):
    policy_id = _insert_user_policy(orm_session, country_id="uk")

    response = _create_test_client().put(
        "/us/user-policy",
        json={"id": policy_id, "reform_label": "wrong country"},
    )

    assert response.status_code == 404
    orm_session.expire_all()
    assert orm_session.get(UserPolicy, policy_id).reform_label == "old label"

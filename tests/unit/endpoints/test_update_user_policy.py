"""Regression tests for issue #3445.

update_user_policy (policy.py) previously interpolated untrusted
payload keys directly into an UPDATE statement, allowing arbitrary
SQL fragments (and identity-column tampering) via the JSON body.

The fix rejects unknown keys with a 400 response and restricts
writable columns to a static whitelist.
"""

import time

from flask import Flask

from policyengine_api.endpoints import update_user_policy


def _create_test_client() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.route("/<country_id>/user-policy", methods=["PUT"])(update_user_policy)
    return app.test_client()


def _insert_user_policy(test_db) -> int:
    now = int(time.time())
    test_db.query(
        "INSERT INTO user_policies (country_id, reform_label, reform_id, "
        "baseline_label, baseline_id, user_id, year, geography, dataset, "
        "number_of_provisions, api_version, added_date, updated_date) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "us",
            "old label",
            2,
            None,
            1,
            "user1",
            "2025",
            "us",
            "cps",
            3,
            "1.0.0",
            now,
            now,
        ),
    )
    row = test_db.query(
        "SELECT id FROM user_policies ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["id"]


def test_update_user_policy_rejects_sql_injection_key(test_db):
    """Unknown keys (including SQL injection attempts) must be rejected."""
    policy_id = _insert_user_policy(test_db)

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
    row = test_db.query(
        "SELECT reform_label FROM user_policies WHERE id = ?",
        (policy_id,),
    ).fetchone()
    assert row["reform_label"] == "old label"


def test_update_user_policy_rejects_identity_column(test_db):
    """Identity columns (user_id, country_id, ...) must not be writable."""
    policy_id = _insert_user_policy(test_db)

    client = _create_test_client()
    response = client.put(
        "/us/user-policy",
        json={"id": policy_id, "user_id": "attacker"},
    )

    assert response.status_code == 400
    row = test_db.query(
        "SELECT user_id FROM user_policies WHERE id = ?",
        (policy_id,),
    ).fetchone()
    assert row["user_id"] == "user1"


def test_update_user_policy_allows_whitelisted_field(test_db):
    """Whitelisted fields (e.g. reform_label) can still be updated."""
    policy_id = _insert_user_policy(test_db)

    client = _create_test_client()
    response = client.put(
        "/us/user-policy",
        json={"id": policy_id, "reform_label": "new label"},
    )

    assert response.status_code == 200
    row = test_db.query(
        "SELECT reform_label FROM user_policies WHERE id = ?",
        (policy_id,),
    ).fetchone()
    assert row["reform_label"] == "new label"


def test_update_user_policy_requires_id(test_db):
    client = _create_test_client()
    response = client.put("/us/user-policy", json={"reform_label": "x"})
    assert response.status_code == 400


def test_update_user_policy_requires_at_least_one_field(test_db):
    policy_id = _insert_user_policy(test_db)
    client = _create_test_client()
    response = client.put("/us/user-policy", json={"id": policy_id})
    assert response.status_code == 400

import time

import pytest
from flask import Flask
from sqlalchemy import select

from policyengine_api.data.v1_models import UserPolicy
from policyengine_api.routes.policy_routes import policy_bp


def create_client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(policy_bp)
    return app.test_client()


@pytest.mark.parametrize("dataset", ["custom_dataset", None])
def test_set_user_policy_persists_dataset_with_orm(orm_session, dataset):
    now = int(time.time())
    response = create_client().post(
        "/us/user-policy",
        json={
            "reform_id": 2,
            "baseline_id": 1,
            "user_id": "user1",
            "year": "2025",
            "geography": "us",
            "dataset": dataset,
            "number_of_provisions": 3,
            "api_version": "1.0.0",
            "added_date": now,
            "updated_date": now,
        },
    )

    assert response.status_code == 201
    orm_session.expire_all()
    policy = orm_session.scalar(select(UserPolicy).where(UserPolicy.user_id == "user1"))
    assert policy.dataset == dataset

import json
from typing import ClassVar

from sqlalchemy import delete

from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import Policy
from policyengine_api.utils import hash_object


class TestPolicyCreation:
    # Define the policy to test against
    country_id = "us"
    policy_json: ClassVar[dict] = {"sample_parameter": {"2024-01-01.2025-12-31": True}}
    label = "dworkin"
    test_policy: ClassVar[dict] = {"data": policy_json, "label": label}
    policy_hash = hash_object(policy_json)

    """
    Test creating a policy, then ensure that duplicating
    that policy generates the correct response within the
    app; this requires sequential processing, hence the
    need for a separate Python-based test
    """

    def test_create_unique_policy(self, api_client):
        with get_v1_session_factory().begin() as session:
            session.execute(
                delete(Policy).where(
                    Policy.policy_hash == self.policy_hash,
                    Policy.label == self.label,
                    Policy.country_id == self.country_id,
                )
            )

        res = api_client.post("/us/policy", json=self.test_policy)
        return_object = json.loads(res.text)

        assert return_object["status"] == "ok"
        assert res.status_code == 201

    def test_create_nonunique_policy(self, api_client):
        res = api_client.post("/us/policy", json=self.test_policy)
        return_object = json.loads(res.text)

        assert return_object["status"] == "ok"
        assert res.status_code == 200

        with get_v1_session_factory().begin() as session:
            session.execute(
                delete(Policy).where(
                    Policy.policy_hash == self.policy_hash,
                    Policy.label == self.label,
                    Policy.country_id == self.country_id,
                )
            )

    def test_create_policy_invalid_country(self, api_client):
        res = api_client.post("/au/policy", json=self.test_policy)
        assert res.status_code == 400

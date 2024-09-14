import pytest
import json
import time
from policyengine_api.data import local_database
from policyengine_api.endpoints.tracer import get_tracer


class TestTracer:
    # Set shared variables
    country_id = "us"
    household_id = 1
    policy_id = 1
    api_version = "1.0.0"
    variable_name = "test_variable"
    tracer_output = {"some": "data"}

    def test_get_tracer(self):
        # Insert test data
        local_database.execute(
            """
            INSERT INTO tracers 
            (household_id, policy_id, country_id, api_version, tracer_output, variable_name)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                self.household_id,
                self.policy_id,
                self.country_id,
                self.api_version,
                json.dumps(self.tracer_output),
                self.variable_name,
            ),
        )
        local_database.commit()

        # Call get_tracer
        result = get_tracer(
            self.country_id,
            self.household_id,
            self.api_version,
            self.variable_name,
            self.policy_id,
        )

        # Assert results
        assert result["status"] == 200
        assert result["result"]["household_id"] == self.household_id
        assert result["result"]["policy_id"] == self.policy_id
        assert result["result"]["country_id"] == self.country_id
        assert result["result"]["api_version"] == self.api_version
        assert result["result"]["variable_name"] == self.variable_name
        assert result["result"]["tracer_output"] == self.tracer_output

        # Clean up
        local_database.execute(
            "DELETE FROM tracers WHERE household_id = ? AND policy_id = ?",
            (self.household_id, self.policy_id),
        )
        local_database.commit()

    def test_get_tracer_not_found(self):
        # Call get_tracer with non-existent data
        result = get_tracer(
            self.country_id,
            999,  # Non-existent household_id
            self.api_version,
            self.variable_name,
            self.policy_id,
        )

        # Assert results
        assert isinstance(result, tuple)
        assert result[1] == 404  # Check status code
        response_body = json.loads(result[0].data)
        assert response_body["status"] == "error"
        assert "Tracer not found" in response_body["message"]

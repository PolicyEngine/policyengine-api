import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

from flask import Flask
import pytest

from policyengine_api.endpoints import household as household_endpoint


RECEIPT_FIXTURE = Path(__file__).parents[2] / "fixtures" / "execution_receipt_v1.json"
HOUSEHOLD_RESULT = {"people": {"you": {"age": {"2026": 40}}}}


class DummyCountry:
    metadata = {"variables": {}, "entities": {}}

    def __init__(self):
        self.calculate_calls = 0

    def calculate(self, household, policy, household_id, policy_id):
        self.calculate_calls += 1
        return deepcopy(HOUSEHOLD_RESULT)


class QueryResult:
    def __init__(self, row=None):
        self.row = row

    def fetchone(self):
        return self.row


@pytest.fixture
def household_policy_client(monkeypatch):
    country = DummyCountry()

    def query(sql, _parameters=None):
        if "SELECT * FROM computed_household" in sql:
            return QueryResult()
        if "FROM household WHERE" in sql:
            return QueryResult(
                {
                    "id": "456",
                    "country_id": "us",
                    "household_json": '{"people": {"you": {}}}',
                }
            )
        if "FROM policy WHERE" in sql:
            return QueryResult(
                {
                    "id": "22",
                    "country_id": "us",
                    "policy_json": "{}",
                }
            )
        return QueryResult()

    database_query = MagicMock(side_effect=query)
    receipt = json.loads(RECEIPT_FIXTURE.read_text())

    monkeypatch.setattr(
        household_endpoint,
        "get_countries",
        lambda: {"us": country},
    )
    monkeypatch.setattr(household_endpoint.database, "query", database_query)
    monkeypatch.setattr(
        household_endpoint,
        "build_household_execution_receipt",
        lambda **_kwargs: deepcopy(receipt),
    )
    monkeypatch.setattr(
        household_endpoint,
        "get_invalid_inputs_response",
        lambda *_args: None,
    )

    app = Flask(__name__)
    app.add_url_rule(
        "/<country_id>/household/<household_id>/policy/<policy_id>",
        "household_under_policy",
        household_endpoint.get_household_under_policy,
        methods=["GET"],
    )
    return (
        app.test_client(),
        country,
        database_query,
        receipt,
    )


def test__fresh_calculation__returns_and_caches_original_execution_receipt(
    household_policy_client,
):
    client, country, database_query, receipt = household_policy_client

    response = client.get("/us/household/456/policy/22")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "message": None,
        "result": HOUSEHOLD_RESULT,
        "execution_receipt": receipt,
    }
    assert country.calculate_calls == 1
    insert_call = next(
        call for call in database_query.call_args_list if "INSERT INTO" in call.args[0]
    )
    insert_parameters = insert_call.args[1]
    cached_value = json.loads(insert_parameters[3])
    assert cached_value == {
        household_endpoint.COMPUTED_HOUSEHOLD_ENVELOPE_KEY: 1,
        "result": HOUSEHOLD_RESULT,
        "execution_receipt": receipt,
    }


def test__receipt_build_failure__returns_and_caches_result_without_receipt(
    household_policy_client,
    monkeypatch,
):
    # Given
    client, country, database_query, _receipt = household_policy_client

    def fail_receipt(**_kwargs):
        raise ValueError("non-finite provenance value")

    monkeypatch.setattr(
        household_endpoint,
        "build_household_execution_receipt",
        fail_receipt,
    )

    # When
    response = client.get("/us/household/456/policy/22")

    # Then
    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "message": None,
        "result": HOUSEHOLD_RESULT,
    }
    assert country.calculate_calls == 1
    insert_call = next(
        call for call in database_query.call_args_list if "INSERT INTO" in call.args[0]
    )
    assert json.loads(insert_call.args[1][3])["execution_receipt"] is None


def test__cache_insert_conflict__updates_receipt_and_api_version(
    household_policy_client,
):
    # Given
    client, _country, database_query, _receipt = household_policy_client
    original_query = database_query.side_effect

    def fail_insert(sql, parameters=None):
        if "INSERT INTO computed_household" in sql:
            raise RuntimeError("duplicate cache key")
        return original_query(sql, parameters)

    database_query.side_effect = fail_insert

    # When
    response = client.get("/us/household/456/policy/22")

    # Then
    assert response.status_code == 200
    update_call = next(
        call
        for call in database_query.call_args_list
        if "UPDATE computed_household" in call.args[0]
    )
    assert "computed_household_json = ?, api_version = ?" in update_call.args[0]
    assert update_call.args[1][1] == household_endpoint.COUNTRY_PACKAGE_VERSIONS["us"]


def test__enveloped_cache_hit__returns_persisted_receipt_without_recalculation(
    monkeypatch,
):
    receipt = json.loads(RECEIPT_FIXTURE.read_text())
    cached_value = household_endpoint._serialize_computed_household(
        HOUSEHOLD_RESULT,
        receipt,
    )
    query = MagicMock(
        return_value=QueryResult(
            {
                "policy_id": "22",
                "household_id": "456",
                "country_id": "us",
                "api_version": "1.0.0",
                "computed_household_json": cached_value,
                "status": "ok",
            }
        )
    )
    monkeypatch.setattr(household_endpoint.database, "query", query)

    response = household_endpoint.get_household_under_policy.__wrapped__(
        "us", "456", "22"
    )

    assert response["result"] == HOUSEHOLD_RESULT
    assert response["execution_receipt"] == receipt
    assert query.call_count == 1


def test__legacy_raw_cache_hit__does_not_fabricate_current_runtime_receipt(
    monkeypatch,
):
    query = MagicMock(
        return_value=QueryResult(
            {
                "policy_id": "22",
                "household_id": "456",
                "country_id": "us",
                "api_version": "1.0.0",
                "computed_household_json": json.dumps(HOUSEHOLD_RESULT),
                "status": "ok",
            }
        )
    )
    monkeypatch.setattr(household_endpoint.database, "query", query)

    response = household_endpoint.get_household_under_policy.__wrapped__(
        "us", "456", "22"
    )

    assert response == {
        "status": "ok",
        "message": None,
        "result": HOUSEHOLD_RESULT,
    }


def test__cache_envelope_with_invalid_receipt__omits_receipt():
    cached_value = household_endpoint._serialize_computed_household(
        HOUSEHOLD_RESULT,
        {"schema_version": 1, "resolved": {}},
    )

    result, receipt = household_endpoint._deserialize_computed_household(cached_value)

    assert result == HOUSEHOLD_RESULT
    assert receipt is None


def test__cache_envelope_with_result_hash_mismatch__omits_receipt():
    # Given
    receipt = json.loads(RECEIPT_FIXTURE.read_text())
    changed_result = {"people": {"you": {"age": {"2026": 41}}}}
    cached_value = household_endpoint._serialize_computed_household(
        changed_result,
        receipt,
    )

    # When
    result, restored_receipt = household_endpoint._deserialize_computed_household(
        cached_value
    )

    # Then
    assert result == changed_result
    assert restored_receipt is None


def test__cache_receipt_verification_failure_returns_result_without_receipt():
    # Given
    receipt = json.loads(RECEIPT_FIXTURE.read_text())
    non_jcs_result = {"value": float("nan")}
    cached_value = household_endpoint._serialize_computed_household(
        non_jcs_result,
        receipt,
    )

    # When
    result, restored_receipt = household_endpoint._deserialize_computed_household(
        cached_value
    )

    # Then
    assert result["value"] != result["value"]
    assert restored_receipt is None

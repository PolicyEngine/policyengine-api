import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from flask import Flask

from policyengine_api.data.orm import build_sqlite_session_manager
from policyengine_api.data.v1_daos import V1UnitOfWork
from policyengine_api.endpoints.household import get_household_under_policy
from policyengine_api.endpoints.policy import (
    get_user_policy,
    set_user_policy,
    update_user_policy,
)
from tests.unit.data.sqlite_schema import create_sqlite_v1_schema


def _unit_of_work() -> V1UnitOfWork:
    manager = build_sqlite_session_manager()
    create_sqlite_v1_schema(manager)
    return V1UnitOfWork(manager)


def _daos_unit_of_work(daos):
    @contextmanager
    def boundary():
        yield daos

    return SimpleNamespace(read=boundary, transaction=boundary)


@pytest.mark.parametrize(
    "stored_result",
    [
        {"people": {"you": {"net_income": {"2026": 42}}}},
        json.dumps({"people": {"you": {"net_income": {"2026": 42}}}}),
    ],
)
def test_household_under_policy_returns_cached_json_objects_and_legacy_strings(
    stored_result,
):
    computed_households = Mock()
    computed_households.get.return_value = {
        "household_id": 1,
        "policy_id": 2,
        "country_id": "us",
        "api_version": "1",
        "computed_household_json": stored_result,
        "status": "complete",
    }
    local_uow = _daos_unit_of_work(
        SimpleNamespace(computed_households=computed_households)
    )

    with patch(
        "policyengine_api.endpoints.household.runtime_v1_unit_of_work",
        return_value=local_uow,
    ) as runtime_uow:
        response = get_household_under_policy("us", "1", "2")

    assert response["result"] == {"people": {"you": {"net_income": {"2026": 42}}}}
    runtime_uow.assert_called_once_with(local=True)


def test_household_under_policy_calculates_and_caches_json_as_an_object():
    computed_households = Mock()
    computed_households.get.return_value = None
    local_uow = _daos_unit_of_work(
        SimpleNamespace(computed_households=computed_households)
    )
    remote_uow = _daos_unit_of_work(
        SimpleNamespace(
            households=SimpleNamespace(
                get=Mock(
                    return_value={
                        "id": 1,
                        "country_id": "us",
                        "household_json": {"people": {"you": {}}},
                    }
                )
            ),
            policies=SimpleNamespace(
                get=Mock(
                    return_value={
                        "id": 2,
                        "country_id": "us",
                        "policy_json": {"gov.example.parameter": 1},
                    }
                )
            ),
        )
    )
    calculated = {"people": {"you": {"net_income": {"2026": 42}}}}
    country = SimpleNamespace(calculate=Mock(return_value=calculated))

    def select_uow(*, local=False):
        return local_uow if local else remote_uow

    with (
        patch(
            "policyengine_api.endpoints.household.runtime_v1_unit_of_work",
            side_effect=select_uow,
        ),
        patch(
            "policyengine_api.endpoints.household.add_yearly_variables",
            side_effect=lambda household, _: household,
        ),
        patch(
            "policyengine_api.endpoints.household.drop_deprecated_inputs",
            side_effect=lambda household: SimpleNamespace(
                household=household,
                warnings=[],
            ),
        ),
        patch(
            "policyengine_api.endpoints.household.get_invalid_inputs_response",
            return_value=None,
        ),
        patch(
            "policyengine_api.endpoints.household.get_countries",
            return_value={"us": country},
        ),
    ):
        response = get_household_under_policy("us", "1", "2")

    assert response["result"] == calculated
    country.calculate.assert_called_once_with(
        {"people": {"you": {}}},
        {"gov.example.parameter": 1},
        "1",
        "2",
    )
    assert (
        computed_households.upsert.call_args.kwargs["computed_household_json"]
        is calculated
    )


def test_user_policy_endpoints_round_trip_through_the_unit_of_work():
    app = Flask(__name__)
    uow = _unit_of_work()
    payload = {
        "reform_label": "Reform",
        "reform_id": 2,
        "baseline_label": "Current law",
        "baseline_id": 1,
        "user_id": "auth0|one",
        "year": "2026",
        "geography": "us",
        "dataset": "default",
        "number_of_provisions": 3,
        "api_version": "1",
        "added_date": 1,
        "updated_date": 1,
        "budgetary_impact": None,
        "type": None,
    }

    with patch(
        "policyengine_api.endpoints.policy.runtime_v1_unit_of_work",
        return_value=uow,
    ):
        with app.test_request_context(json=payload):
            created = set_user_policy("us")
        listed = get_user_policy("us", "auth0|one")
        with app.test_request_context(json={"id": 1, "reform_label": "Updated"}):
            updated = update_user_policy("us")

    assert created.status_code == 201
    assert created.get_json()["result"]["dataset"] == "default"
    assert listed["result"][0]["reform_label"] == "Reform"
    assert updated.status_code == 200
    with uow.read() as daos:
        assert daos.user_policies.get(1)["reform_label"] == "Updated"

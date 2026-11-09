"""Pin which /calculate and /calculate-full responses the HTTP cache stores."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from policyengine_core.errors import SituationParsingError

from policyengine_api.extensions import cache
from policyengine_api.routes import household_routes
from policyengine_api.services.household_calculation_service import (
    HouseholdCalculationResult,
    InvalidHouseholdInputsError,
)
from policyengine_api.utils.input_validation import UnrecognizedInput

if TYPE_CHECKING:
    from collections.abc import Callable

    from flask.testing import FlaskClient

CALCULATION_PATHS = ("/us/calculate", "/us/calculate-full")
PAYLOAD = {"household": {"people": {"you": {}}}, "policy": {}}
SUCCESS = HouseholdCalculationResult(household={"people": {"you": {}}}, warnings=())


@pytest.fixture
def calculation_service(monkeypatch) -> MagicMock:
    service = MagicMock()
    monkeypatch.setattr(household_routes, "household_calculation_service", service)
    return service


@pytest.fixture
def client() -> FlaskClient:
    """Return a client whose calculation responses go through an in-memory cache."""
    app = Flask(__name__)
    app.config.update(TESTING=True, CACHE_TYPE="SimpleCache")
    cache.init_app(app)
    app.register_blueprint(household_routes.household_bp)
    with app.app_context():
        cache.clear()
    return app.test_client()


def _fail_calculation(service: MagicMock, error: Exception) -> None:
    service.calculate_prepared_household.side_effect = [error, SUCCESS, SUCCESS]


def _fail_parsing(service: MagicMock, error: Exception) -> None:
    service.parse_prepared_household.side_effect = [error, MagicMock(), MagicMock()]
    service.calculate_prepared_household.return_value = SUCCESS


FAILURES: dict[str, tuple[Callable[[MagicMock, Exception], None], Exception, int]] = {
    "calculation raises": (_fail_calculation, RuntimeError("engine exploded"), 500),
    "parsing raises": (_fail_parsing, RuntimeError("parser exploded"), 500),
    "household rejected": (
        _fail_calculation,
        SituationParsingError(["people"], "people must be an object"),
        400,
    ),
    "input unrecognised": (
        _fail_calculation,
        InvalidHouseholdInputsError(
            [
                UnrecognizedInput(
                    input_type="policy_parameter",
                    name="gov.unknown",
                    path="policy.gov.unknown",
                )
            ]
        ),
        400,
    ),
}


@pytest.mark.parametrize("path", CALCULATION_PATHS)
def test_a_successful_calculation_is_served_from_the_cache(
    client: FlaskClient,
    calculation_service: MagicMock,
    path: str,
) -> None:
    calculation_service.calculate_prepared_household.return_value = SUCCESS

    first = client.post(path, json=PAYLOAD)
    replay = client.post(path, json=PAYLOAD)

    assert first.status_code == replay.status_code == 200
    assert replay.get_json() == first.get_json()
    assert calculation_service.calculate_prepared_household.call_count == 1


@pytest.mark.parametrize("failure", sorted(FAILURES))
@pytest.mark.parametrize("path", CALCULATION_PATHS)
def test_a_failed_calculation_is_computed_again_on_the_next_request(
    client: FlaskClient,
    calculation_service: MagicMock,
    path: str,
    failure: str,
) -> None:
    arrange_failure, error, failed_status = FAILURES[failure]
    arrange_failure(calculation_service, error)

    failed = client.post(path, json=PAYLOAD)
    retried = client.post(path, json=PAYLOAD)
    replay = client.post(path, json=PAYLOAD)

    assert failed.status_code == failed_status
    assert retried.status_code == replay.status_code == 200
    assert replay.get_json() == retried.get_json()
    # The failure isn't replayed; the success after it is.
    assert calculation_service.calculate_prepared_household.call_count == (
        1 if failure == "parsing raises" else 2
    )
    assert calculation_service.parse_prepared_household.call_count == 2


@pytest.mark.parametrize("path", CALCULATION_PATHS)
def test_a_repeated_server_error_is_logged_on_every_request(
    client: FlaskClient,
    calculation_service: MagicMock,
    path: str,
) -> None:
    calculation_service.calculate_prepared_household.side_effect = RuntimeError(
        "engine exploded"
    )

    with patch.object(household_routes, "module_logger") as module_logger:
        responses = [client.post(path, json=PAYLOAD) for _ in range(2)]

    assert [response.status_code for response in responses] == [500, 500]
    assert calculation_service.calculate_prepared_household.call_count == 2
    assert module_logger.exception.call_count == 2

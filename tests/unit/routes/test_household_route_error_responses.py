"""Pin every error response of the stored-household and calculate routes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from policyengine_core.errors import SituationParsingError

from policyengine_api.extensions import cache
from policyengine_api.routes import household_routes
from policyengine_api.services.household_calculation_service import (
    HouseholdCalculationResult,
    HouseholdNotFoundError,
    InvalidHouseholdInputsError,
    PolicyNotFoundError,
)
from policyengine_api.spm import SPMValidationError
from policyengine_api.utils.input_validation import UnrecognizedInput

INVALID_INPUT = UnrecognizedInput(
    input_type="policy_parameter",
    name="gov.unknown",
    path="policy.gov.unknown",
)
INVALID_INPUTS_BODY = {
    "status": "error",
    "message": f"Unrecognized calculate input(s): {INVALID_INPUT.message}",
    "result": None,
    "errors": [INVALID_INPUT.to_dict()],
}
SPM_ERROR = SPMValidationError("SPM_SETTINGS_INVALID", "spm is malformed")
SPM_BODY = {
    "status": "error",
    "message": "spm is malformed",
    "result": None,
    "errors": [{"code": "SPM_SETTINGS_INVALID", "message": "spm is malformed"}],
}
PARSING_ERROR = SituationParsingError(["people"], "people must be an object")


@pytest.fixture
def calculation_service(monkeypatch) -> MagicMock:
    service = MagicMock()
    monkeypatch.setattr(household_routes, "household_calculation_service", service)
    monkeypatch.setattr(household_routes, "get_v1_household_read_source", MagicMock())
    return service


@pytest.fixture
def client():
    app = Flask(__name__)
    app.config.update(TESTING=True, CACHE_TYPE="NullCache")
    cache.init_app(app)
    app.register_blueprint(household_routes.household_bp)
    return app.test_client()


@pytest.mark.parametrize(
    ("error", "status_code", "body"),
    [
        (
            HouseholdNotFoundError(),
            404,
            {"status": "error", "message": "Household #3 not found."},
        ),
        (
            PolicyNotFoundError(),
            404,
            {"status": "error", "message": "Policy #4 not found."},
        ),
        (InvalidHouseholdInputsError([INVALID_INPUT]), 400, INVALID_INPUTS_BODY),
        (SPM_ERROR, 400, SPM_BODY),
        (
            RuntimeError("engine exploded"),
            500,
            {
                "status": "error",
                "message": "Error calculating household #3 under policy #4: "
                "engine exploded",
            },
        ),
    ],
)
def test_stored_household_calculation_errors_map_to_responses(
    client,
    calculation_service: MagicMock,
    error: Exception,
    status_code: int,
    body: dict[str, object],
) -> None:
    calculation_service.calculate_stored_household.side_effect = error

    with patch.object(household_routes, "module_logger") as module_logger:
        response = client.get("/us/household/3/policy/4")

    assert response.status_code == status_code
    assert response.get_json() == body
    if status_code == 500:
        module_logger.exception.assert_called_once_with(
            "Error calculating household #%s under policy #%s", "3", "4"
        )
    else:
        module_logger.exception.assert_not_called()


def test_stored_household_calculation_needs_a_valid_read_source(
    client,
    calculation_service: MagicMock,
) -> None:
    household_routes.get_v1_household_read_source.side_effect = ValueError("bad")

    response = client.get("/us/household/3/policy/4")

    assert response.status_code == 503
    assert response.get_json() == {
        "status": "error",
        "message": "Household persistence configuration is unavailable.",
    }
    calculation_service.calculate_stored_household.assert_not_called()


def test_stored_household_calculation_success_returns_the_result(
    client,
    calculation_service: MagicMock,
) -> None:
    calculation_service.calculate_stored_household.return_value = (
        HouseholdCalculationResult(household={"people": {}}, warnings=("late",))
    )

    response = client.get("/us/household/3/policy/4")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "message": None,
        "result": {"people": {}},
        "warnings": ["late"],
    }
    assert calculation_service.calculate_stored_household.call_args.args == (
        "us",
        3,
        4,
    )


@pytest.mark.parametrize(
    ("error", "status_code", "body"),
    [
        (
            PARSING_ERROR,
            400,
            {
                "status": "error",
                "message": f"Invalid household payload: {PARSING_ERROR}",
                "result": None,
            },
        ),
        (SPM_ERROR, 400, SPM_BODY),
        (
            RuntimeError("parser exploded"),
            500,
            {
                "status": "error",
                "message": "Error calculating household under policy: parser exploded",
            },
        ),
    ],
)
def test_calculation_parse_errors_map_to_responses(
    client,
    calculation_service: MagicMock,
    error: Exception,
    status_code: int,
    body: dict[str, object],
) -> None:
    calculation_service.parse_prepared_household.side_effect = error

    with (
        patch.object(household_routes, "module_logger") as module_logger,
        patch.object(household_routes, "start_observability_id") as start_observability,
    ):
        response = client.post("/us/calculate", json={"household": {}})

    assert response.status_code == status_code
    assert response.get_json() == body
    assert start_observability.call_count == int(status_code == 500)
    assert module_logger.exception.call_count == int(status_code == 500)
    calculation_service.calculate_prepared_household.assert_not_called()


@pytest.mark.parametrize(
    ("error", "status_code", "body"),
    [
        (InvalidHouseholdInputsError([INVALID_INPUT]), 400, INVALID_INPUTS_BODY),
        (
            PARSING_ERROR,
            400,
            {
                "status": "error",
                "message": f"Invalid household payload: {PARSING_ERROR}",
                "result": None,
            },
        ),
        (SPM_ERROR, 400, SPM_BODY),
        (
            RuntimeError("engine exploded"),
            500,
            {
                "status": "error",
                "message": "Error calculating household under policy: engine exploded",
            },
        ),
    ],
)
def test_calculation_errors_map_to_responses(
    client,
    calculation_service: MagicMock,
    error: Exception,
    status_code: int,
    body: dict[str, object],
) -> None:
    calculation_service.calculate_prepared_household.side_effect = error

    with (
        patch.object(household_routes, "module_logger") as module_logger,
        patch.object(household_routes, "start_observability_id") as start_observability,
    ):
        response = client.post("/us/calculate-full", json={"household": {}})

    assert response.status_code == status_code
    assert response.get_json() == body
    start_observability.assert_not_called()
    if status_code == 500:
        module_logger.exception.assert_called_once_with(
            "Error calculating household under policy"
        )
    else:
        module_logger.exception.assert_not_called()


def test_situation_parsing_error_caused_by_spm_returns_the_spm_error(
    client,
    calculation_service: MagicMock,
) -> None:
    parsing_error = SituationParsingError(["spm"], "spm is malformed")
    parsing_error.__cause__ = SPM_ERROR
    calculation_service.calculate_prepared_household.side_effect = parsing_error

    response = client.post("/us/calculate", json={"household": {}})

    assert response.status_code == 400
    assert response.get_json() == {
        **SPM_BODY,
        "message": "spm is malformed",
    }

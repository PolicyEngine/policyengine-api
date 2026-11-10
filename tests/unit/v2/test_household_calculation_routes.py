"""The native ``/v2/household-calculations`` routes and their error answers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from flask import Flask

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.data.v2.settings import V2ConfigurationError
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.household_calculations.types import (
    HouseholdCalculationFailure,
    HouseholdCalculationOutput,
    HouseholdCalculationRead,
    HouseholdCalculationSubmitted,
    SimulationServiceAnswerUnreadableError,
    SimulationServiceInternalError,
    SimulationServiceInvalidRequestError,
    SimulationServiceUnavailableError,
)
from policyengine_api.services.v2.household_calculations.validators import (
    HouseholdCalculationCountryError,
    HouseholdCalculationNotFoundError,
    HouseholdCalculationResultUnreadableError,
    HouseholdCalculationStorageError,
    HouseholdCalculationYearError,
)
from policyengine_api.services.v2.households.validators import HouseholdNotFoundError
from policyengine_api.services.v2.policies.validators import (
    PolicyNotFoundError,
    PolicyParametersMissingError,
)
from tests.fixtures.household_calculation_documents import (
    CALCULATED_HOUSEHOLD,
    INPUT_ERROR,
    JOB_ID,
    SPM_CONFIG,
    SPM_PROVENANCE,
    WARNING,
)
from tests.unit.v2.household_calculation_support import (
    CATALOG_VERSION_ID,
    CREATED_AT,
    HOUSEHOLD_ID,
    POLICY_ID,
    REFORMED_PARAMETER,
)

COMPLETED_AT = datetime(2026, 11, 10, 12, 0, 9, tzinfo=UTC)
CALCULATIONS = "/v2/household-calculations"


def _read(**changes: object) -> HouseholdCalculationRead:
    fields: dict[str, object] = {
        "calculation_id": JOB_ID,
        "country_id": "us",
        "household_id": HOUSEHOLD_ID,
        "policy_id": POLICY_ID,
        "year": 2026,
        "catalog_version_id": CATALOG_VERSION_ID,
        "country_package_version": "1.450.0",
        "policyengine_version": "6.10.0",
        "status": "succeeded",
        "created_at": CREATED_AT,
        "started_at": CREATED_AT,
        "completed_at": COMPLETED_AT,
        "result": HouseholdCalculationOutput(
            household=CALCULATED_HOUSEHOLD,
            warnings=(WARNING,),
            spm_config=SPM_CONFIG,
            spm_provenance=SPM_PROVENANCE,
        ),
        "error": None,
    }
    fields.update(changes)
    return HouseholdCalculationRead(**fields)


class FakeCalculationService:
    """The household calculation service, with scripted answers and errors."""

    def __init__(self) -> None:
        self.submissions: list = []
        self.reads: list = []
        self.error: Exception | None = None
        self.read_answer = _read()

    def submit_calculation(self, calculation) -> HouseholdCalculationSubmitted:
        self.submissions.append(calculation)
        if self.error is not None:
            raise self.error
        return HouseholdCalculationSubmitted(
            calculation_id=JOB_ID,
            status="pending",
            country_id=calculation.country_id,
            household_id=calculation.household_id,
            policy_id=calculation.policy_id,
            year=2026,
        )

    def get_calculation(self, calculation_id) -> HouseholdCalculationRead:
        self.reads.append(calculation_id)
        if self.error is not None:
            raise self.error
        return self.read_answer


def _client(service_factory) -> TestClient:
    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        v2_household_calculation_service_factory=service_factory,
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    return TestClient(
        create_asgi_app(
            Flask(__name__), dependencies=dependencies, route_settings=settings
        ),
        raise_server_exceptions=False,
    )


@pytest.fixture
def service() -> FakeCalculationService:
    return FakeCalculationService()


@pytest.fixture
def client(service) -> TestClient:
    return _client(lambda: service)


def _body(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "country_id": "us",
        "household_id": str(HOUSEHOLD_ID),
        "policy_id": str(POLICY_ID),
    }
    body.update(changes)
    return body


def test_a_calculation_is_accepted_without_an_account(client, service) -> None:
    response = client.post(CALCULATIONS, json=_body(country_id="US"))

    assert response.status_code == 202
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {
            "item": {
                "calculation_id": str(JOB_ID),
                "status": "pending",
                "country_id": "us",
                "household_id": str(HOUSEHOLD_ID),
                "policy_id": str(POLICY_ID),
                "year": 2026,
            }
        },
    }
    (calculation,) = service.submissions
    assert calculation.country_id == "us"
    assert calculation.household_id == HOUSEHOLD_ID
    assert calculation.policy_id == POLICY_ID


def test_axes_options_and_spm_settings_reach_the_service(client, service) -> None:
    axis = {"name": "employment_income", "count": 3, "min": 0, "max": 9_000}

    response = client.post(
        CALCULATIONS,
        json=_body(
            policy_id=None,
            axes=[[axis]],
            add_missing_variables=True,
            spm={"scenario": "ce_trend"},
        ),
    )

    assert response.status_code == 202
    (calculation,) = service.submissions
    assert calculation.policy_id is None
    assert calculation.add_missing_variables is True
    assert calculation.axes is not None
    assert calculation.axes[0][0].model_dump(exclude_unset=True) == axis
    assert calculation.spm.model_dump(mode="json") == {"scenario": "ce_trend"}


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"household_id": None}, id="no-household"),
        pytest.param({"unknown": 1}, id="unknown-field"),
        pytest.param({"spm": None}, id="null-spm"),
        pytest.param(
            {
                "axes": [
                    [
                        {"name": "a", "count": 2, "min": 0, "max": 1},
                        {"name": "b", "count": 3, "min": 0, "max": 1},
                    ]
                ]
            },
            id="uneven-axes",
        ),
        pytest.param({"country_id": "ca"}, id="unsupported-country"),
    ],
)
def test_a_malformed_request_is_refused_before_anything_is_read(
    client, service, changes
) -> None:
    response = client.post(CALCULATIONS, json=_body(**changes))

    assert response.status_code == 422
    assert response.json() == {"status": "error", "message": "Invalid API v2 request"}
    assert service.submissions == []


@pytest.mark.parametrize(
    ("error", "status_code", "message"),
    [
        (
            HouseholdCalculationCountryError("No household calculations for uk."),
            422,
            "No household calculations for uk.",
        ),
        (
            HouseholdCalculationYearError("This household has no default year."),
            422,
            "This household has no default year.",
        ),
        (
            SimulationServiceInvalidRequestError("The service cannot calculate it."),
            422,
            "The service cannot calculate it.",
        ),
        (HouseholdNotFoundError("Household not found."), 404, "Household not found."),
        (PolicyNotFoundError("Policy not found."), 404, "Policy not found."),
        (
            SimulationServiceUnavailableError("The simulation service answered 503."),
            503,
            "The simulation service answered 503.",
        ),
        (
            HouseholdCalculationStorageError("storage down"),
            503,
            "V2 household calculation storage is unavailable",
        ),
        (
            SimulationServiceAnswerUnreadableError(
                "The simulation service accepted the calculation, but its "
                "answer could not be read."
            ),
            502,
            "The simulation service accepted the calculation, but its "
            "answer could not be read.",
        ),
        (
            SimulationServiceInternalError("The simulation service failed."),
            502,
            "The simulation service failed.",
        ),
        (
            RuntimeError("secret detail"),
            500,
            "V2 household calculation failed",
        ),
    ],
)
def test_a_refused_submission_gets_its_error_answer(
    client, service, error, status_code, message
) -> None:
    service.error = error

    response = client.post(CALCULATIONS, json=_body())

    assert response.status_code == status_code
    assert response.json() == {"status": "error", "message": message}


def test_a_policy_with_missing_parameters_is_refused_with_their_names(
    client, service
) -> None:
    service.error = PolicyParametersMissingError(POLICY_ID, (REFORMED_PARAMETER,))

    response = client.post(CALCULATIONS, json=_body())

    assert response.status_code == 422
    assert response.json() == {
        "status": "error",
        "message": (
            f"Policy {POLICY_ID} sets parameters the running catalog version "
            f"does not have: {REFORMED_PARAMETER}"
        ),
        "code": "missing_parameters",
        "missing_parameters": [REFORMED_PARAMETER],
    }


def test_v2_storage_that_is_not_configured_answers_503() -> None:
    def unconfigured():
        msg = "V2_RUNTIME_DATABASE_URL is required"
        raise V2ConfigurationError(msg)

    client = _client(unconfigured)

    submitted = client.post(CALCULATIONS, json=_body())
    read = client.get(f"{CALCULATIONS}/{JOB_ID}")

    assert [submitted.status_code, read.status_code] == [503, 503]
    assert read.json() == {
        "status": "error",
        "message": "V2 household calculation storage is unavailable",
    }


def test_a_succeeded_calculation_reads_back_its_household(client, service) -> None:
    response = client.get(f"{CALCULATIONS}/{JOB_ID}")

    assert response.status_code == 200
    assert service.reads == [JOB_ID]
    item = response.json()["result"]["item"]
    assert item == {
        "calculation_id": str(JOB_ID),
        "country_id": "us",
        "household_id": str(HOUSEHOLD_ID),
        "policy_id": str(POLICY_ID),
        "year": 2026,
        "catalog_version_id": str(CATALOG_VERSION_ID),
        "country_package_version": "1.450.0",
        "policyengine_version": "6.10.0",
        "status": "succeeded",
        "created_at": "2026-11-10T12:00:00Z",
        "started_at": "2026-11-10T12:00:00Z",
        "completed_at": "2026-11-10T12:00:09Z",
        "result": {
            "household": CALCULATED_HOUSEHOLD,
            "warnings": [WARNING],
            "spm_config": SPM_CONFIG,
            "spm_provenance": SPM_PROVENANCE,
        },
        "error": None,
    }
    assert list(item["result"]["household"]["people"]["person-1"]) == [
        "employment_income",
        "age",
    ]


def test_a_failed_calculation_reads_back_its_error(client, service) -> None:
    service.read_answer = _read(
        status="failed",
        result=None,
        error=HouseholdCalculationFailure(
            code="invalid_inputs",
            message="The household names a variable the model lacks.",
            input_errors=(INPUT_ERROR,),
            spm_error=None,
        ),
    )

    response = client.get(f"{CALCULATIONS}/{JOB_ID}")

    assert response.status_code == 200
    item = response.json()["result"]["item"]
    assert item["status"] == "failed"
    assert item["result"] is None
    assert item["error"] == {
        "code": "invalid_inputs",
        "message": "The household names a variable the model lacks.",
        "input_errors": [INPUT_ERROR],
        "spm_error": None,
    }


@pytest.mark.parametrize(
    ("error", "status_code", "message"),
    [
        (
            HouseholdCalculationNotFoundError("Household calculation not found."),
            404,
            "Household calculation not found.",
        ),
        (
            HouseholdCalculationResultUnreadableError("unreadable"),
            500,
            "Stored household calculation result is unreadable",
        ),
        (
            HouseholdCalculationStorageError("storage down"),
            503,
            "V2 household calculation storage is unavailable",
        ),
    ],
)
def test_a_calculation_that_cannot_be_read_gets_its_error_answer(
    client, service, error, status_code, message
) -> None:
    service.error = error

    response = client.get(f"{CALCULATIONS}/{uuid4()}")

    assert response.status_code == status_code
    assert response.json() == {"status": "error", "message": message}


def test_a_calculation_id_that_is_not_a_uuid_is_refused(client, service) -> None:
    response = client.get(f"{CALCULATIONS}/not-a-uuid")

    assert response.status_code == 422
    assert service.reads == []


def test_openapi_documents_both_routes_and_the_missing_parameter_refusal(
    client,
) -> None:
    schema = client.get("/v2/openapi.json").json()

    submit = schema["paths"][CALCULATIONS]["post"]
    read = schema["paths"][f"{CALCULATIONS}/{{calculation_id}}"]["get"]
    assert set(submit["responses"]) >= {"202", "404", "422", "500", "502", "503"}
    assert set(read["responses"]) >= {"200", "404", "422", "500", "503"}
    assert "security" not in submit
    refusal_schema = submit["responses"]["422"]["content"]["application/json"]["schema"]
    refusals = {option["$ref"].rsplit("/", 1)[-1] for option in refusal_schema["anyOf"]}
    assert refusals == {"V2ErrorResponse", "V2MissingParametersErrorResponse"}
    missing_parameters = schema["components"]["schemas"][
        "V2MissingParametersErrorResponse"
    ]
    assert set(missing_parameters["properties"]) == {
        "status",
        "message",
        "code",
        "missing_parameters",
    }

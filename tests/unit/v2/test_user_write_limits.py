"""Request-size and field bounds on user-owned writes."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from pydantic import ValidationError
import pytest

from policyengine_api.fastapi_routes.v2.user_resources import (
    MAXIMUM_USER_WRITE_REQUEST_BYTES,
)
from policyengine_api.services.v2.associations.types import (
    ASSOCIATION_DESCRIPTION_MAX_LENGTH,
)
from policyengine_api.services.v2.user_households.types import (
    UserHouseholdCreateFields,
    UserHouseholdUpdateInput,
)
from policyengine_api.services.v2.user_policies.types import (
    UserPolicyCreateFields,
    UserPolicyUpdateInput,
)
from policyengine_api.services.v2.user_reports.types import (
    MAXIMUM_CALIBRATION_MATCHES,
    MAXIMUM_SCORECARD_PROGRAMS,
    REPORT_SOURCE_NOTE_MAX_LENGTH,
    ReportValidation,
    UserReportCreateFields,
    UserReportUpdateInput,
)
from policyengine_api.services.v2.user_simulations.types import (
    UserSimulationCreateFields,
    UserSimulationRead,
    UserSimulationUpdateInput,
)
from tests.unit.v2.user_route_support import (
    CREATED_AT,
    OWNER_ID,
    RecordingService,
    user_route_client,
)


UUID_PATH_VALUE = "00000000-0000-0000-0000-000000000001"


def _services() -> tuple[dict[str, RecordingService], dict[str, Any]]:
    services = {
        name: RecordingService()
        for name in ("account", "policy", "household", "simulation", "report")
    }
    factories = {
        "v2_account_service_factory": lambda: services["account"],
        "v2_user_policy_service_factory": lambda: services["policy"],
        "v2_user_household_service_factory": lambda: services["household"],
        "v2_user_simulation_service_factory": lambda: services["simulation"],
        "v2_user_report_service_factory": lambda: services["report"],
    }
    return services, factories


def _user_write_operations() -> list[tuple[str, str]]:
    _services_by_name, factories = _services()
    client, _flask_calls = user_route_client(**factories)
    paths = client.get("/v2/openapi.json").json()["paths"]
    operations = [
        (method.upper(), path.replace("{association_id}", UUID_PATH_VALUE))
        for path, methods in paths.items()
        if path.startswith(("/v2/me", "/v2/user-"))
        for method in methods
        if method in {"post", "patch"}
    ]
    assert len(operations) >= 10
    return sorted(operations)


def _padded_body(size: int) -> bytes:
    body = json.dumps({"description": "x" * size}).encode()
    assert len(body) > size
    return body


@pytest.mark.parametrize(("method", "path"), _user_write_operations())
def test_every_user_write_rejects_oversized_bodies_before_the_service(
    method: str, path: str
) -> None:
    services, factories = _services()
    client, _flask_calls = user_route_client(**factories)

    response = client.request(
        method,
        f"{path}?country_id=us",
        content=_padded_body(MAXIMUM_USER_WRITE_REQUEST_BYTES),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["status"] == "error"
    assert all(not service.calls for service in services.values())


def test_single_writes_accept_bodies_under_the_limit() -> None:
    services, factories = _services()
    description = "x" * ASSOCIATION_DESCRIPTION_MAX_LENGTH
    services["simulation"].next_result = UserSimulationRead(
        id=UUID(UUID_PATH_VALUE),
        country_id="us",
        user_id=OWNER_ID,
        simulation_id=None,
        legacy_simulation_id=613,
        name=None,
        description=description,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )
    client, _flask_calls = user_route_client(**factories)

    response = client.post(
        "/v2/user-simulations?country_id=us",
        content=json.dumps(
            {
                "country_id": "us",
                "legacy_simulation_id": 613,
                "description": description,
            }
        ),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 201
    assert response.json()["result"]["item"]["description"] == description


@pytest.mark.parametrize(
    ("model", "fields"),
    [
        (UserPolicyCreateFields, {"country_id": "us", "legacy_policy_id": 1}),
        (UserPolicyUpdateInput, {}),
        (UserHouseholdCreateFields, {"country_id": "us", "legacy_household_id": 1}),
        (UserHouseholdUpdateInput, {}),
        (
            UserSimulationCreateFields,
            {"country_id": "us", "legacy_simulation_id": 1},
        ),
        (UserSimulationUpdateInput, {}),
        (UserReportCreateFields, {"country_id": "us", "legacy_report_id": 1}),
        (UserReportUpdateInput, {}),
    ],
)
def test_descriptions_are_bounded_on_every_caller_input(model, fields) -> None:
    model.model_validate(
        {**fields, "description": "x" * ASSOCIATION_DESCRIPTION_MAX_LENGTH}
    )
    with pytest.raises(ValidationError):
        model.model_validate(
            {**fields, "description": "x" * (ASSOCIATION_DESCRIPTION_MAX_LENGTH + 1)}
        )


@pytest.mark.parametrize("model", [UserReportCreateFields, UserReportUpdateInput])
def test_report_source_notes_are_bounded(model) -> None:
    fields = {"country_id": "us", "legacy_report_id": 1}
    allowed = set(model.model_fields)
    base = {name: value for name, value in fields.items() if name in allowed}
    model.model_validate({**base, "source_note": "x" * REPORT_SOURCE_NOTE_MAX_LENGTH})
    with pytest.raises(ValidationError):
        model.model_validate(
            {**base, "source_note": "x" * (REPORT_SOURCE_NOTE_MAX_LENGTH + 1)}
        )


def _validation(*, matches: int = 1, programs: int = 1, **overrides: Any) -> dict:
    match = {
        "variable": "income_tax",
        "depth": 0,
        "ring": "primary",
        "target_count": 2,
        "mean_abs_relative_error": 0.1,
        "worst": {"name": "irs", "source": "soi", "geography": "US"},
    }
    return {
        "matched_at": "2026-10-12T00:00:00Z",
        "map_model_version": "1",
        "calibration": {
            "geography": "US",
            "reached_count": matches,
            "matches": [match] * matches,
        },
        "scorecard": {"programs": ["snap"] * programs},
        **overrides,
    }


def test_report_validation_bounds_list_lengths_and_strings() -> None:
    ReportValidation.model_validate(
        _validation(
            matches=MAXIMUM_CALIBRATION_MATCHES, programs=MAXIMUM_SCORECARD_PROGRAMS
        )
    )
    for too_large in (
        _validation(matches=MAXIMUM_CALIBRATION_MATCHES + 1),
        _validation(programs=MAXIMUM_SCORECARD_PROGRAMS + 1),
        _validation(matched_at="x" * 65),
        _validation(map_model_version="x" * 256),
    ):
        with pytest.raises(ValidationError):
            ReportValidation.model_validate(too_large)


NON_FINITE_NUMBERS = [float("nan"), float("inf"), float("-inf")]


def _provision(**overrides: Any) -> dict:
    return {
        "path": "gov.irs.credits.ctc.amount",
        "breadcrumb": "Child Tax Credit amount",
        "baseline_value": 2000,
        "value": 3000,
        **overrides,
    }


@pytest.mark.parametrize("number", NON_FINITE_NUMBERS)
@pytest.mark.parametrize(
    "provision",
    [
        lambda number: _provision(baseline_value=number),
        lambda number: _provision(value={"nested": [1, number]}),
        lambda number: _provision(
            intervals=[
                {"start_date": "2026-01-01", "end_date": "2026-12-31", "value": number}
            ]
        ),
    ],
)
def test_report_provisions_reject_non_finite_numbers(provision, number) -> None:
    fields = {"country_id": "us", "legacy_report_id": 1}
    with pytest.raises(ValidationError):
        UserReportCreateFields.model_validate(
            {**fields, "provisions": [provision(number)]}
        )


@pytest.mark.parametrize("number", NON_FINITE_NUMBERS)
def test_report_validation_rejects_non_finite_numbers(number) -> None:
    worst = {"name": "irs", "source": "soi", "geography": "US"}
    match = {
        "variable": "income_tax",
        "depth": 0,
        "ring": "primary",
        "target_count": 2,
        "mean_abs_relative_error": 0.1,
        "worst": worst,
    }
    for snapshot in (
        _validation(
            calibration={
                "geography": "US",
                "reached_count": 1,
                "matches": [{**match, "mean_abs_relative_error": number}],
            }
        ),
        _validation(
            calibration={
                "geography": "US",
                "reached_count": 1,
                "matches": [{**match, "worst": {**worst, "relative_error": number}}],
            }
        ),
    ):
        with pytest.raises(ValidationError):
            ReportValidation.model_validate(snapshot)


def test_finite_json_values_keep_their_types() -> None:
    provision = UserReportCreateFields.model_validate(
        {
            "country_id": "us",
            "legacy_report_id": 1,
            "provisions": [
                _provision(value={"rate": 0.25, "flag": True, "count": 3, "label": "x"})
            ],
        }
    ).provisions[0]

    assert provision.value == {"rate": 0.25, "flag": True, "count": 3, "label": "x"}
    assert isinstance(provision.value["flag"], bool)
    assert isinstance(provision.value["count"], int)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_single_writes_with_non_finite_json_numbers_are_rejected(token) -> None:
    services, factories = _services()
    client, _flask_calls = user_route_client(**factories)

    response = client.post(
        "/v2/user-reports?country_id=us",
        content=(
            '{"country_id": "us", "legacy_report_id": 615, "provisions": '
            '[{"path": "a", "breadcrumb": "b", "baseline_value": '
            f'{token}, "value": 1}}]}}'
        ),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert not services["report"].calls

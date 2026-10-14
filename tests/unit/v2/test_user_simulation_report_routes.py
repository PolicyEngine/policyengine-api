"""Native FastAPI contract tests for signed-in simulation and report saves."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from policyengine_api.services.v2.associations.validators import (
    AssociationLinkNotFoundError,
)
from policyengine_api.services.v2.legacy_refs.validators import (
    LegacyReferenceNotFoundError,
)
from policyengine_api.services.v2.user_reports.types import (
    UserReportPage,
    UserReportRead,
)
from policyengine_api.services.v2.user_reports.validators import (
    UserReportNotFoundError,
)
from policyengine_api.services.v2.user_simulations.types import (
    UserSimulationPage,
    UserSimulationRead,
)
from tests.unit.v2.user_route_support import (
    CREATED_AT,
    OWNER_ID,
    PRINCIPAL,
    RecordingService,
    user_route_client,
)


SIMULATION_ASSOCIATION_ID = UUID("00000000-0000-0000-0000-000000000062")
REPORT_ASSOCIATION_ID = UUID("00000000-0000-0000-0000-000000000063")
USER_POLICY_ID = UUID("00000000-0000-0000-0000-000000000064")
LAST_RUN_AT = datetime(2026, 2, 1, 12, tzinfo=timezone.utc)
PROVISIONS = [
    {
        "path": "gov.irs.credits.ctc.amount",
        "breadcrumb": "Child Tax Credit amount",
        "unit": "currency-USD",
        "baseline_value": 2000,
        "value": 3000,
        "intervals": [
            {"start_date": "2026-01-01", "end_date": "2026-12-31", "value": 3000}
        ],
    }
]
VALIDATION = {
    "matched_at": "2026-02-01T12:00:00Z",
    "map_model_version": "1",
    "calibration": {
        "release_id": None,
        "geography": "us",
        "reached_count": 1,
        "matches": [
            {
                "variable": "ctc",
                "depth": 1,
                "ring": "primary",
                "target_count": 3,
                "mean_abs_relative_error": 0.1,
                "worst": {
                    "name": "ctc_total",
                    "source": "irs",
                    "geography": "us",
                    "relative_error": None,
                },
            }
        ],
    },
    "scorecard": {"programs": ["ctc"]},
}


def _simulation_read() -> UserSimulationRead:
    return UserSimulationRead(
        id=SIMULATION_ASSOCIATION_ID,
        country_id="us",
        user_id=OWNER_ID,
        simulation_id=None,
        legacy_simulation_id=613,
        name="Baseline",
        description=None,
        created_at=CREATED_AT,
        updated_at=CREATED_AT + timedelta(seconds=1),
    )


def _report_read() -> UserReportRead:
    return UserReportRead(
        id=REPORT_ASSOCIATION_ID,
        country_id="us",
        user_id=OWNER_ID,
        report_id=None,
        legacy_report_id=615,
        name="CTC report",
        description=None,
        user_policy_id=USER_POLICY_ID,
        source_note="from chat",
        provisions=PROVISIONS,
        validation=VALIDATION,
        budget_window_years=10,
        last_run_at=LAST_RUN_AT,
        created_at=CREATED_AT,
        updated_at=CREATED_AT + timedelta(seconds=1),
    )


def _simulation_result(name: str, kwargs: dict):
    if name == "list_user_simulations":
        return UserSimulationPage(
            items=(_simulation_read(),),
            offset=kwargs["offset"],
            limit=kwargs["limit"],
            has_more=False,
        )
    return None if name.startswith("delete") else _simulation_read()


def _report_result(name: str, kwargs: dict):
    if name == "list_user_reports":
        return UserReportPage(
            items=(_report_read(),),
            offset=kwargs["offset"],
            limit=kwargs["limit"],
            has_more=False,
        )
    return None if name.startswith("delete") else _report_read()


def _clients():
    simulations = RecordingService(_simulation_result)
    reports = RecordingService(_report_result)
    client, _flask_calls = user_route_client(
        v2_user_simulation_service_factory=lambda: simulations,
        v2_user_report_service_factory=lambda: reports,
    )
    return client, simulations, reports


def test_simulation_routes_require_v1_references_and_scope_to_the_user() -> None:
    client, simulations, _reports = _clients()

    created = client.post(
        "/v2/user-simulations?country_id=us",
        json={"country_id": "us", "legacy_simulation_id": 613},
    )
    v2_reference = client.post(
        "/v2/user-simulations?country_id=us",
        json={"country_id": "us", "simulation_id": str(SIMULATION_ASSOCIATION_ID)},
    )
    listed = client.get("/v2/user-simulations?country_id=us&legacy_simulation_id=613")
    patched = client.patch(
        f"/v2/user-simulations/{SIMULATION_ASSOCIATION_ID}?country_id=us",
        json={"legacy_simulation_id": 614, "description": "Repointed"},
    )
    deleted = client.delete(
        f"/v2/user-simulations/{SIMULATION_ASSOCIATION_ID}?country_id=us"
    )

    assert created.status_code == 201
    assert created.json()["result"]["item"] == {
        "id": str(SIMULATION_ASSOCIATION_ID),
        "country_id": "us",
        "user_id": str(OWNER_ID),
        "simulation_id": None,
        "legacy_simulation_id": 613,
        "name": "Baseline",
        "description": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:01Z",
    }
    assert v2_reference.status_code == 422
    assert listed.status_code == 200
    assert patched.status_code == 200
    assert deleted.status_code == 204
    assert [call[0] for call in simulations.calls] == [
        "create_user_simulation",
        "list_user_simulations",
        "patch_user_simulation",
        "delete_user_simulation",
    ]
    assert all(call[1]["principal"] == PRINCIPAL for call in simulations.calls)
    assert simulations.calls[1][1]["legacy_simulation_id"] == 613


def test_report_routes_round_trip_v3_fields() -> None:
    client, _simulations, reports = _clients()

    created = client.post(
        "/v2/user-reports?country_id=us",
        json={
            "country_id": "us",
            "legacy_report_id": 615,
            "name": "CTC report",
            "user_policy_id": str(USER_POLICY_ID),
            "source_note": "from chat",
            "provisions": PROVISIONS,
            "validation": VALIDATION,
            "budget_window_years": 10,
            "last_run_at": "2026-02-01T12:00:00Z",
        },
    )

    assert created.status_code == 201
    item = created.json()["result"]["item"]
    assert item["legacy_report_id"] == 615
    assert item["report_id"] is None
    assert item["user_policy_id"] == str(USER_POLICY_ID)
    assert item["provisions"] == PROVISIONS
    assert item["validation"] == VALIDATION
    assert item["budget_window_years"] == 10
    assert item["last_run_at"] == "2026-02-01T12:00:00Z"
    fields = reports.calls[0][1]["association_input"]
    assert fields.provisions[0].intervals[0].value == 3000
    assert fields.validation.calibration.matches[0].ring == "primary"


@pytest.mark.parametrize(
    "changes",
    [
        {"report_id": str(REPORT_ASSOCIATION_ID)},
        {"legacy_report_id": None},
        {"user_id": str(OWNER_ID)},
        {"last_run_at": "2026-02-01T12:00:00"},
        {"provisions": [{"path": "x", "breadcrumb": "y"}]},
        {"provisions": [{**PROVISIONS[0], "extra": True}]},
        {
            "provisions": [
                {**PROVISIONS[0], "intervals": [{"start_date": "2026", "value": 1}]}
            ]
        },
        {"validation": {**VALIDATION, "scorecard": {"programs": "ctc"}}},
        {"provisions": [{**PROVISIONS[0], "value": "x" * (64 * 1024)}]},
        {"budget_window_years": 1},
        {"budget_window_years": 76},
        {"budget_window_years": "ten"},
    ],
)
def test_report_create_rejects_invalid_v3_payloads(changes: dict) -> None:
    client, _simulations, reports = _clients()
    body = {"country_id": "us", "legacy_report_id": 615, **changes}

    response = client.post("/v2/user-reports?country_id=us", json=body)

    assert response.status_code == 422
    assert reports.calls == []


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (AssociationLinkNotFoundError("user-policy association was not found"), 422),
        (LegacyReferenceNotFoundError("v1 report 615 was not found"), 422),
        (UserReportNotFoundError("association was not found"), 404),
    ],
)
def test_report_failures_map_to_contract_statuses(
    error: Exception, status: int
) -> None:
    client, _simulations, reports = _clients()
    reports.error = error

    response = client.patch(
        f"/v2/user-reports/{REPORT_ASSOCIATION_ID}?country_id=us",
        json={"user_policy_id": str(USER_POLICY_ID)},
    )

    assert response.status_code == status
    assert response.json()["status"] == "error"


def test_report_patch_accepts_only_contract_fields() -> None:
    client, _simulations, reports = _clients()

    accepted = client.patch(
        f"/v2/user-reports/{REPORT_ASSOCIATION_ID}?country_id=us",
        json={
            "legacy_report_id": 616,
            "user_policy_id": None,
            "provisions": None,
            "budget_window_years": None,
            "last_run_at": "2026-03-01T00:00:00+00:00",
        },
    )
    rejected = client.patch(
        f"/v2/user-reports/{REPORT_ASSOCIATION_ID}?country_id=us",
        json={"client_ref": "sur-2"},
    )

    assert accepted.status_code == 200
    assert rejected.status_code == 422
    association_input = reports.calls[0][1]["association_input"]
    assert association_input.model_fields_set == {
        "legacy_report_id",
        "user_policy_id",
        "provisions",
        "budget_window_years",
        "last_run_at",
    }


def test_report_snapshots_echo_stored_keys_with_contract_nulls() -> None:
    sparse_provision = {
        "path": "gov.irs.credits.ctc.amount",
        "breadcrumb": "Child Tax Credit amount",
        "baseline_value": 2000,
        "value": 3000,
        "intervals": [
            {"start_date": "2026-01-01", "end_date": "2026-12-31", "value": 3000}
        ],
    }
    sparse_validation = {"matched_at": "2026-02-01T12:00:00Z", "map_model_version": "1"}
    reports = RecordingService(
        lambda _name, _kwargs: replace(
            _report_read(),
            provisions=[sparse_provision],
            validation=sparse_validation,
        )
    )
    client, _flask_calls = user_route_client(
        v2_user_report_service_factory=lambda: reports
    )

    item = client.get(f"/v2/user-reports/{REPORT_ASSOCIATION_ID}?country_id=us").json()[
        "result"
    ]["item"]

    # Nullable contract keys are present; the optional interval parameter
    # stays absent rather than null.
    assert item["provisions"] == [{**sparse_provision, "unit": None}]
    assert "parameter" not in item["provisions"][0]["intervals"][0]
    assert item["validation"] == {
        **sparse_validation,
        "calibration": None,
        "scorecard": None,
    }


def test_openapi_types_report_and_policy_snapshots() -> None:
    client, _simulations, _reports = _clients()

    schemas = client.get("/v2/openapi.json").json()["components"]["schemas"]

    def property_refs(schema_name: str, field_name: str) -> set[str]:
        field = schemas[schema_name]["properties"][field_name]
        options = field.get("anyOf", [field])
        refs = set()
        for option in options:
            target = option.get("items", option)
            if "$ref" in target:
                refs.add(target["$ref"].rsplit("/", 1)[-1])
        return refs

    report_item = next(name for name in schemas if name.startswith("UserReportItem"))
    policy_item = next(name for name in schemas if name.startswith("UserPolicyItem"))
    assert {
        name.split("-")[0] for name in property_refs(report_item, "provisions")
    } == {"ReportProvisionItem"}
    assert {
        name.split("-")[0] for name in property_refs(report_item, "validation")
    } == {"ReportValidationItem"}
    assert {
        name.split("-")[0] for name in property_refs(policy_item, "provenance")
    } == {"PolicyProvenanceItem"}


def test_stored_snapshots_outside_input_bounds_still_serialize() -> None:
    long_label = "x" * 5_000
    match = {
        "variable": long_label,
        "depth": 0,
        "ring": "a-ring-added-later",
        "target_count": 1,
        "mean_abs_relative_error": 0.1,
        "worst": {"name": long_label, "source": "irs", "geography": "us"},
    }
    oversized_validation = {
        "matched_at": long_label,
        "map_model_version": "1",
        "retired_key": "kept in storage, dropped from responses",
        "calibration": {
            "geography": long_label,
            "reached_count": 600,
            "matches": [match] * 600,
        },
        "scorecard": {"programs": ["snap"] * 500},
    }
    odd_read = replace(_report_read(), validation=oversized_validation)
    reports = RecordingService(
        lambda _name, kwargs: UserReportPage(
            items=(odd_read, _report_read()),
            offset=kwargs["offset"],
            limit=kwargs["limit"],
            has_more=False,
        )
    )
    client, _flask_calls = user_route_client(
        v2_user_report_service_factory=lambda: reports
    )

    response = client.get("/v2/user-reports?country_id=us")

    assert response.status_code == 200
    first, second = response.json()["result"]["items"]
    assert len(first["validation"]["calibration"]["matches"]) == 600
    assert first["validation"]["calibration"]["geography"] == long_label
    assert "retired_key" not in first["validation"]
    assert second["validation"] == VALIDATION

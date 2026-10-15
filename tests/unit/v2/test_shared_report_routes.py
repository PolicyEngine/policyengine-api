"""Native FastAPI contract tests for reading a saved report by its link."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from policyengine_api.migration_flags import infer_route_group
from policyengine_api.services.v2.user_reports.types import (
    SharedBaselineReformRead,
    SharedUserReportRead,
)
from policyengine_api.services.v2.user_reports.validators import (
    UserReportNotFoundError,
)
from tests.unit.v2.user_route_support import (
    CREATED_AT,
    RecordingService,
    user_route_client,
)


REPORT_ASSOCIATION_ID = UUID("00000000-0000-0000-0000-000000000063")
SHARED_PATH = f"/v2/shared-reports/{REPORT_ASSOCIATION_ID}"
LAST_RUN_AT = datetime(2026, 2, 1, 12, tzinfo=timezone.utc)
PROVISIONS = [
    {
        "path": "gov.irs.credits.ctc.amount",
        "breadcrumb": "Child Tax Credit amount",
        "unit": "currency-USD",
        "baseline_value": 2000,
        "value": 3000,
    }
]


def _shared_report_read() -> SharedUserReportRead:
    return SharedUserReportRead(
        id=REPORT_ASSOCIATION_ID,
        country_id="us",
        legacy_report_id=615,
        name="CTC report",
        source_note="from chat",
        provisions=PROVISIONS,
        validation=None,
        budget_window_years=10,
        baseline_reform=SharedBaselineReformRead(name="Current plan"),
        last_run_at=LAST_RUN_AT,
        created_at=CREATED_AT,
        updated_at=CREATED_AT + timedelta(seconds=1),
    )


def _shared_client(reports: RecordingService):
    # The default authenticator fails closed: no credential is ever accepted.
    client, _flask_calls = user_route_client(
        require_user=None,
        v2_user_report_service_factory=lambda: reports,
    )
    return client


def test_anyone_reads_a_saved_report_by_its_link_without_the_owner() -> None:
    reports = RecordingService(_shared_report_read())
    client = _shared_client(reports)

    shared = client.get(f"{SHARED_PATH}?country_id=us")
    owner_read = client.get(f"/v2/user-reports/{REPORT_ASSOCIATION_ID}?country_id=us")

    assert shared.status_code == 200
    assert shared.json() == {
        "status": "ok",
        "message": None,
        "result": {
            "item": {
                "id": str(REPORT_ASSOCIATION_ID),
                "country_id": "us",
                "legacy_report_id": 615,
                "name": "CTC report",
                "source_note": "from chat",
                "provisions": [{**PROVISIONS[0], "intervals": None}],
                "validation": None,
                "budget_window_years": 10,
                "baseline_reform": {"name": "Current plan"},
                "last_run_at": "2026-02-01T12:00:00Z",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:01Z",
            }
        },
    }
    assert reports.calls == [
        (
            "get_shared_user_report",
            {"country_id": "us", "association_id": REPORT_ASSOCIATION_ID},
        )
    ]
    # The owner's own routes still need a credential.
    assert owner_read.status_code == 401


def test_a_link_to_no_saved_report_is_not_found() -> None:
    reports = RecordingService()
    reports.error = UserReportNotFoundError(
        f"user-report association {REPORT_ASSOCIATION_ID} was not found"
    )
    client = _shared_client(reports)

    response = client.get(f"{SHARED_PATH}?country_id=uk")

    assert response.status_code == 404
    assert response.json()["status"] == "error"
    assert reports.calls[0][1]["country_id"] == "uk"


@pytest.mark.parametrize(
    "path",
    [
        SHARED_PATH,
        f"{SHARED_PATH}?country_id=us&user_id=00000000-0000-0000-0000-000000000070",
        f"{SHARED_PATH}?country_id=us&country_id=uk",
        f"{SHARED_PATH}?country_id=xx",
        "/v2/shared-reports/615?country_id=us",
    ],
)
def test_shared_report_queries_and_ids_are_validated(path: str) -> None:
    reports = RecordingService(_shared_report_read())
    client = _shared_client(reports)

    response = client.get(path)

    assert response.status_code == 422
    assert reports.calls == []


def test_shared_reports_are_logged_with_reports() -> None:
    assert infer_route_group(SHARED_PATH) == "report"


def test_openapi_documents_the_shared_read_without_security() -> None:
    client = _shared_client(RecordingService(_shared_report_read()))

    operation = client.get("/v2/openapi.json").json()["paths"][
        "/v2/shared-reports/{association_id}"
    ]["get"]

    assert "security" not in operation
    assert set(operation["responses"]) == {"200", "404", "422", "500", "503"}
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "association_id",
        "country_id",
    ]

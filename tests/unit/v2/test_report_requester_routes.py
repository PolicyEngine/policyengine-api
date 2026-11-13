"""Who asks for a report's run: the optional user credential, over stand-ins."""

from __future__ import annotations

from uuid import uuid4

import pytest

from policyengine_api.libs.user_auth import UNAUTHENTICATED_USER_HEADER
from policyengine_api.services.v2.identity.types import UnauthenticatedPrincipal
from policyengine_api.services.v2.identity.validators import (
    StandardUserRequiresSignInError,
)
from policyengine_api.services.v2.stored_reports.validators import (
    ReportRunNotRecordedError,
    RerunReportUnreadableError,
)
from tests.unit.v2.report_run_support import FakeReportRunService
from tests.unit.v2.stored_report_support import (
    POLICY_ID,
    REPORT_ID,
    REPORT_RUN_ID,
    report_route_client,
)

REPORT_BODY = {
    "country_id": "us",
    "kind": "economy",
    "label": "Expanded child tax credit",
    "year": 2026,
    "region_code": "state/ca",
    "baseline": {},
    "reform": {"policy_id": str(POLICY_ID)},
}


def test_a_signed_out_browsers_create_and_rerun_name_its_user() -> None:
    browser_id = uuid4()
    service = FakeReportRunService()
    client = report_route_client(reports=service)
    headers = {UNAUTHENTICATED_USER_HEADER: str(browser_id)}

    created = client.post(
        "/v2/reports?country_id=us", json=REPORT_BODY, headers=headers
    )
    rerun = client.post(
        f"/v2/reports/{REPORT_ID}/runs?country_id=us", json={}, headers=headers
    )

    assert (created.status_code, rerun.status_code) == (201, 201)
    assert service.requesters == [
        UnauthenticatedPrincipal(user_id=browser_id),
        UnauthenticatedPrincipal(user_id=browser_id),
    ]


def test_a_request_without_a_user_credential_names_no_user() -> None:
    service = FakeReportRunService()
    client = report_route_client(reports=service)

    created = client.post("/v2/reports?country_id=us", json=REPORT_BODY)
    rerun = client.post(f"/v2/reports/{REPORT_ID}/runs?country_id=us", json={})

    assert (created.status_code, rerun.status_code) == (201, 201)
    assert service.requesters == [None, None]


def test_a_malformed_browser_credential_is_refused_before_the_service() -> None:
    service = FakeReportRunService()

    response = report_route_client(reports=service).post(
        "/v2/reports?country_id=us",
        json=REPORT_BODY,
        headers={UNAUTHENTICATED_USER_HEADER: "not-a-uuid"},
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Bearer")
    assert service.calls == []


def test_a_browser_credential_naming_a_signed_in_user_answers_401() -> None:
    service = FakeReportRunService(
        error=StandardUserRequiresSignInError("Sign in to act on this account")
    )

    response = report_route_client(reports=service).post(
        f"/v2/reports/{REPORT_ID}/runs?country_id=us",
        json={},
        headers={UNAUTHENTICATED_USER_HEADER: str(uuid4())},
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["message"] == "Sign in to act on this account"


def test_a_run_whose_request_was_not_recorded_answers_503_naming_it() -> None:
    not_recorded = ReportRunNotRecordedError(
        report_id=REPORT_ID, run_id=REPORT_RUN_ID, country_id="us"
    )
    service = FakeReportRunService(error=not_recorded)
    client = report_route_client(reports=service)

    for response in (
        client.post("/v2/reports?country_id=us", json=REPORT_BODY),
        client.post(f"/v2/reports/{REPORT_ID}/runs?country_id=us", json={}),
    ):
        assert response.status_code == 503
        assert response.json() == {
            "status": "error",
            "message": str(not_recorded),
            "report_id": str(REPORT_ID),
            "run_id": str(REPORT_RUN_ID),
        }


@pytest.mark.parametrize(
    ("path", "method"),
    [("/v2/reports", "post"), ("/v2/reports/{report_id}/runs", "post")],
)
def test_openapi_says_the_user_credential_is_optional(path: str, method: str) -> None:
    document = report_route_client(reports=FakeReportRunService()).get(
        "/v2/openapi.json"
    )

    security = document.json()["paths"][path][method]["security"]
    assert {} in security
    assert {"UserAccessToken": []} in security
    assert {"UnauthenticatedUser": []} in security


def test_a_window_rerun_whose_answer_named_no_window_run_answers_a_null_run() -> None:
    service = FakeReportRunService(
        error=RerunReportUnreadableError(
            report_id=REPORT_ID, run_id=None, country_id="us"
        )
    )

    response = report_route_client(reports=service).post(
        f"/v2/reports/{REPORT_ID}/runs?country_id=us", json={}
    )

    assert response.status_code == 502
    body = response.json()
    assert body["run_id"] is None
    assert f"/v2/reports/{REPORT_ID}?country_id=us rather" in body["message"]


def test_openapi_documents_the_reruns_nullable_run_and_the_reads_403() -> None:
    document = (
        report_route_client(reports=FakeReportRunService())
        .get("/v2/openapi.json")
        .json()
    )

    rerun_unreadable = document["components"]["schemas"][
        "RerunReportUnreadableResponse"
    ]
    assert {"type": "null"} in rerun_unreadable["properties"]["run_id"]["anyOf"]
    assert "run_id" in rerun_unreadable["required"]
    for path in ("/v2/reports", "/v2/reports/{report_id}"):
        assert "403" in document["paths"][path]["get"]["responses"], path

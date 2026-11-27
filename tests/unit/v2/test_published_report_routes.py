"""Routes that publish a saved report, and the public read of a published report.

The owner's routes take a user credential. Publishing, editing and moving a
page to a newer run need author or above; reading the owner's page and
withdrawing it need only ownership. Anyone reads a published report, with no
credential, by its saved report's ID.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from policyengine_api.data.v2.models import UserType
from policyengine_api.migration_flags import infer_route_group
from policyengine_api.services.v2.published_reports.types import (
    PublicationRead,
    PublicationVersionRead,
    PublishedReportRead,
    PublishedSavedReportRead,
)
from policyengine_api.services.v2.published_reports.validators import (
    PublicationExistsError,
    PublicationNotFoundError,
    PublicationRunAlreadyShownError,
    PublicationRunNotFoundError,
    PublicationRunNotSucceededError,
    PublishedReportNotFoundError,
    PublishedReportStorageError,
    PublishedVersionNotFoundError,
    UnpublishableUserReportError,
)
from policyengine_api.services.v2.stored_reports.economy_results.types import (
    EconomyResultUnreadableError,
)
from policyengine_api.services.v2.user_reports.types import SharedBaselineReformRead
from policyengine_api.services.v2.user_reports.validators import (
    PublishedUserReportRepointError,
    UserReportNotFoundError,
)
from policyengine_api.services.v2.user_types.validators import (
    UserTypeBelowMinimumError,
)
from tests.unit.v2.published_report_support import (
    PROVISIONS,
    publication_body,
    without_run,
)
from tests.unit.v2.stored_report_support import (
    FakeReportService,
    report_read,
    report_route_client,
    report_run_read,
)
from tests.unit.v2.user_route_support import (
    PRINCIPAL,
    RecordingService,
    user_route_client,
)

USER_REPORT_ID = UUID("00000000-0000-0000-0000-000000000063")
RUN_ID = UUID("00000000-0000-0000-0000-000000000064")
VERSION_ID = UUID("00000000-0000-0000-0000-000000000065")
PUBLICATION_PATH = f"/v2/user-reports/{USER_REPORT_ID}/publication"
PUBLIC_PATH = f"/v2/published-reports/{USER_REPORT_ID}"
PUBLISHED_AT = datetime(2026, 11, 28, 9, tzinfo=UTC)
CONTENT = [
    {"type": "markdown", "markdown": "## Why this reform"},
    {"type": "output", "output": "budgetary_impact"},
]
VERSION = PublicationVersionRead(
    id=VERSION_ID,
    run_id=RUN_ID,
    country_package_version="1.5.0",
    policyengine_version="4.2.0",
    published_at=PUBLISHED_AT,
)
EXPECTED_VERSION = {
    "id": str(VERSION_ID),
    "run_id": str(RUN_ID),
    "country_package_version": "1.5.0",
    "policyengine_version": "4.2.0",
    "published_at": "2026-11-28T09:00:00Z",
}


def _publication() -> PublicationRead:
    return PublicationRead(
        user_report_id=USER_REPORT_ID,
        country_id="us",
        summary="What a larger child tax credit costs.",
        author_ids=["nikhil-woodruff"],
        tags=["us"],
        content=CONTENT,
        show_past_versions=False,
        versions=(VERSION,),
        published_at=PUBLISHED_AT,
        updated_at=PUBLISHED_AT + timedelta(hours=1),
    )


EXPECTED_PUBLICATION = {
    "user_report_id": str(USER_REPORT_ID),
    "country_id": "us",
    "summary": "What a larger child tax credit costs.",
    "author_ids": ["nikhil-woodruff"],
    "tags": ["us"],
    "content": CONTENT,
    "show_past_versions": False,
    "versions": [EXPECTED_VERSION],
    "published_at": "2026-11-28T09:00:00Z",
    "updated_at": "2026-11-28T10:00:00Z",
}


def _published_report() -> PublishedReportRead:
    return PublishedReportRead(
        id=USER_REPORT_ID,
        country_id="us",
        title="Expanded child tax credit",
        summary="What a larger child tax credit costs.",
        author_ids=["nikhil-woodruff"],
        tags=["us"],
        content=CONTENT,
        show_past_versions=False,
        saved_report=PublishedSavedReportRead(
            source_note="From the chat",
            provisions=PROVISIONS,
            validation=None,
            budget_window_years=None,
            baseline_reform=SharedBaselineReformRead(name="Plan A"),
        ),
        version=VERSION,
        versions=(VERSION,),
        published_at=PUBLISHED_AT,
        updated_at=PUBLISHED_AT + timedelta(hours=1),
        report=report_read(
            label="Expanded child tax credit", run=report_run_read(id=RUN_ID)
        ),
    )


def _client(
    publications: RecordingService | None = None,
    user_types: RecordingService | None = None,
    **client_options: Any,
):
    publications = publications or RecordingService(_publication())
    user_types = user_types or RecordingService(UserType.AUTHOR)
    client, _flask_calls = user_route_client(
        v2_published_report_service_factory=lambda: publications,
        v2_user_type_service_factory=lambda: user_types,
        **client_options,
    )
    return client, publications, user_types


AUTHOR_CHECK = (
    "require_minimum_user_type",
    {"principal": PRINCIPAL, "minimum": UserType.AUTHOR},
)


def test_an_author_publishes_a_saved_report() -> None:
    client, publications, user_types = _client()

    response = client.post(
        f"{PUBLICATION_PATH}?country_id=us", json=publication_body(RUN_ID)
    )

    assert response.status_code == 201
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {"item": EXPECTED_PUBLICATION},
    }
    assert user_types.calls == [AUTHOR_CHECK]
    ((method, arguments),) = publications.calls
    assert method == "publish_report"
    assert arguments["principal"] == PRINCIPAL
    assert arguments["country_id"] == "us"
    assert arguments["user_report_id"] == USER_REPORT_ID
    assert arguments["publication_input"].run_id == RUN_ID
    assert arguments["publication_input"].tags == ["us", "child-tax-credit"]


def test_the_author_edits_the_page_and_moves_it_to_another_run() -> None:
    client, publications, user_types = _client()

    edited = client.patch(
        f"{PUBLICATION_PATH}?country_id=us", json={"show_past_versions": True}
    )
    moved = client.post(
        f"{PUBLICATION_PATH}/versions?country_id=us", json={"run_id": str(RUN_ID)}
    )

    assert edited.status_code == 200
    assert edited.json()["result"]["item"] == EXPECTED_PUBLICATION
    assert moved.status_code == 201
    assert moved.json()["result"]["item"] == EXPECTED_PUBLICATION
    assert user_types.calls == [AUTHOR_CHECK, AUTHOR_CHECK]
    assert [method for method, _arguments in publications.calls] == [
        "update_publication",
        "add_publication_version",
    ]
    edit = publications.calls[0][1]["publication_input"]
    assert edit.model_fields_set == {"show_past_versions"}
    assert publications.calls[1][1]["version_input"].run_id == RUN_ID


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", PUBLICATION_PATH, publication_body(RUN_ID)),
        ("PATCH", PUBLICATION_PATH, {"tags": []}),
        ("POST", f"{PUBLICATION_PATH}/versions", {"run_id": str(RUN_ID)}),
    ],
)
def test_publishing_editing_and_moving_need_author_or_above(
    method: str, path: str, body: dict[str, Any]
) -> None:
    user_types = RecordingService()
    user_types.error = UserTypeBelowMinimumError("Only authors and admins may do this")
    client, publications, _user_types = _client(user_types=user_types)

    response = client.request(method, f"{path}?country_id=us", json=body)

    assert response.status_code == 403
    assert response.json()["message"] == "Only authors and admins may do this"
    assert publications.calls == []


def test_the_owner_reads_and_withdraws_the_page_whatever_their_type() -> None:
    client, publications, user_types = _client()

    read = client.get(f"{PUBLICATION_PATH}?country_id=us")
    publications.next_result = None
    withdrawn = client.delete(f"{PUBLICATION_PATH}?country_id=us")

    assert read.status_code == 200
    assert read.json()["result"]["item"] == EXPECTED_PUBLICATION
    assert withdrawn.status_code == 204
    assert withdrawn.content == b""
    assert user_types.calls == []
    assert publications.calls == [
        (
            "get_publication",
            {
                "principal": PRINCIPAL,
                "country_id": "us",
                "user_report_id": USER_REPORT_ID,
            },
        ),
        (
            "withdraw_publication",
            {
                "principal": PRINCIPAL,
                "country_id": "us",
                "user_report_id": USER_REPORT_ID,
            },
        ),
    ]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", PUBLICATION_PATH),
        ("GET", PUBLICATION_PATH),
        ("PATCH", PUBLICATION_PATH),
        ("DELETE", PUBLICATION_PATH),
        ("POST", f"{PUBLICATION_PATH}/versions"),
    ],
)
def test_the_owner_routes_need_a_credential(method: str, path: str) -> None:
    client, publications, user_types = _client(require_user=None)

    response = client.request(method, f"{path}?country_id=us", json={})

    assert response.status_code == 401
    assert publications.calls == []
    assert user_types.calls == []


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (UserReportNotFoundError("no saved report"), 404),
        (PublicationNotFoundError("not published"), 404),
        (PublicationRunNotFoundError("not one of its runs"), 404),
        (PublicationExistsError("already published"), 409),
        (UnpublishableUserReportError("names only a v1 report"), 409),
        (PublicationRunNotSucceededError("still running"), 409),
        (PublicationRunAlreadyShownError("already shown"), 409),
    ],
)
def test_the_services_refusals_answer_their_status(
    error: Exception, status: int
) -> None:
    publications = RecordingService()
    publications.error = error
    client, _publications, _user_types = _client(publications)

    response = client.post(
        f"{PUBLICATION_PATH}?country_id=us", json=publication_body(RUN_ID)
    )

    assert response.status_code == status
    assert response.json()["message"] == str(error)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", PUBLICATION_PATH, publication_body(RUN_ID, author_ids=["Ada"])),
        ("POST", PUBLICATION_PATH, without_run(publication_body(RUN_ID))),
        ("PATCH", PUBLICATION_PATH, {"summary": None}),
        ("PATCH", PUBLICATION_PATH, {"run_id": str(RUN_ID)}),
        ("POST", f"{PUBLICATION_PATH}/versions", {"run_id": "615"}),
        ("POST", f"{PUBLICATION_PATH}/versions", {}),
    ],
)
def test_a_malformed_body_is_refused(
    method: str, path: str, body: dict[str, Any]
) -> None:
    client, publications, _user_types = _client()

    response = client.request(method, f"{path}?country_id=us", json=body)

    assert response.status_code == 422
    assert publications.calls == []


@pytest.mark.parametrize(
    "query",
    ["", "?country_id=xx", "?country_id=us&country_id=uk", "?country_id=us&user=1"],
)
def test_the_owner_routes_check_their_query(query: str) -> None:
    client, publications, _user_types = _client()

    response = client.get(f"{PUBLICATION_PATH}{query}")

    assert response.status_code == 422
    assert publications.calls == []


def test_a_page_of_the_largest_allowed_size_is_accepted() -> None:
    client, publications, _user_types = _client()
    content = [{"type": "markdown", "markdown": "m" * 20_000}] * 100

    response = client.post(
        f"{PUBLICATION_PATH}?country_id=us",
        json=publication_body(RUN_ID, content=content),
    )

    assert response.status_code == 201
    assert len(publications.calls[0][1]["publication_input"].content) == 100


def test_a_body_over_four_mebibytes_is_refused() -> None:
    client, publications, _user_types = _client()

    response = client.post(
        f"{PUBLICATION_PATH}?country_id=us",
        content=b"{" + b" " * (4 * 1024 * 1024) + b"}",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413
    assert publications.calls == []


def test_repointing_a_published_saved_report_answers_a_conflict() -> None:
    user_reports = RecordingService()
    user_reports.error = PublishedUserReportRepointError(
        "Withdraw the published report first"
    )
    client, _flask_calls = user_route_client(
        v2_user_report_service_factory=lambda: user_reports
    )

    response = client.patch(
        f"/v2/user-reports/{USER_REPORT_ID}?country_id=us",
        json={"report_id": str(RUN_ID)},
    )

    assert response.status_code == 409
    assert response.json()["message"] == "Withdraw the published report first"


def _public_client(publications: RecordingService):
    # The default authenticator fails closed: no credential is ever accepted.
    client, _publications, user_types = _client(publications, require_user=None)
    return client, user_types


def _report_as_its_route_answers(published: PublishedReportRead) -> dict[str, Any]:
    """Return the report as GET /v2/reports/{id}?run_id= answers it."""
    response = report_route_client(
        reports=FakeReportService(report=published.report)
    ).get(f"/v2/reports/{published.report.id}?country_id=us&run_id={RUN_ID}")
    assert response.status_code == 200
    item: dict[str, Any] = response.json()["result"]["item"]
    return item


def test_anyone_reads_a_published_report_without_its_owner() -> None:
    published = _published_report()
    publications = RecordingService(published)
    client, user_types = _public_client(publications)

    response = client.get(f"{PUBLIC_PATH}?country_id=us")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "message": None,
        "result": {
            "item": {
                "id": str(USER_REPORT_ID),
                "country_id": "us",
                "title": "Expanded child tax credit",
                "summary": "What a larger child tax credit costs.",
                "author_ids": ["nikhil-woodruff"],
                "tags": ["us"],
                "content": CONTENT,
                "show_past_versions": False,
                "saved_report": {
                    "source_note": "From the chat",
                    "provisions": [{**PROVISIONS[0], "intervals": None}],
                    "validation": None,
                    "budget_window_years": None,
                    "baseline_reform": {"name": "Plan A"},
                },
                "version": EXPECTED_VERSION,
                "versions": [EXPECTED_VERSION],
                "published_at": "2026-11-28T09:00:00Z",
                "updated_at": "2026-11-28T10:00:00Z",
                "report": _report_as_its_route_answers(published),
            }
        },
    }
    assert publications.calls == [
        (
            "get_published_report",
            {"country_id": "us", "user_report_id": USER_REPORT_ID, "version_id": None},
        )
    ]
    assert user_types.calls == []


def test_a_reader_names_the_version_to_read() -> None:
    publications = RecordingService(_published_report())
    client, _user_types = _public_client(publications)

    response = client.get(f"{PUBLIC_PATH}?country_id=us&version_id={VERSION_ID}")

    assert response.status_code == 200
    assert publications.calls[0][1]["version_id"] == VERSION_ID


@pytest.mark.parametrize(
    "path",
    [
        PUBLIC_PATH,
        f"{PUBLIC_PATH}?country_id=xx",
        f"{PUBLIC_PATH}?country_id=us&version_id=615",
        f"{PUBLIC_PATH}?country_id=us&run_id={RUN_ID}",
        f"{PUBLIC_PATH}?country_id=us&version_id={VERSION_ID}&version_id={RUN_ID}",
        "/v2/published-reports/615?country_id=us",
    ],
)
def test_the_public_read_checks_its_query_and_id(path: str) -> None:
    publications = RecordingService(_published_report())
    client, _user_types = _public_client(publications)

    response = client.get(path)

    assert response.status_code == 422
    assert publications.calls == []


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (PublishedReportNotFoundError("not published"), 404, "not published"),
        (PublishedVersionNotFoundError("no such version"), 404, "no such version"),
        (
            PublishedReportStorageError("down"),
            503,
            "V2 report storage is unavailable",
        ),
        (
            EconomyResultUnreadableError("bad rows"),
            500,
            "The report's stored result cannot be read",
        ),
    ],
)
def test_the_public_reads_failures_answer_their_status(
    error: Exception, status: int, message: str
) -> None:
    publications = RecordingService()
    publications.error = error
    client, _user_types = _public_client(publications)

    response = client.get(f"{PUBLIC_PATH}?country_id=us")

    assert response.status_code == status
    assert response.json()["message"] == message


def test_published_reports_are_logged_with_reports() -> None:
    assert infer_route_group(PUBLIC_PATH) == "report"
    assert infer_route_group(PUBLICATION_PATH) == "report"


def test_openapi_documents_the_public_read_without_security() -> None:
    client, _publications, _user_types = _client()

    paths = client.get("/v2/openapi.json").json()["paths"]

    public = paths["/v2/published-reports/{user_report_id}"]["get"]
    assert "security" not in public
    assert set(public["responses"]) == {"200", "404", "422", "500", "503"}
    assert [parameter["name"] for parameter in public["parameters"]] == [
        "user_report_id",
        "country_id",
        "version_id",
    ]
    owner = paths["/v2/user-reports/{association_id}/publication"]
    assert set(owner) == {"post", "get", "patch", "delete"}
    assert set(owner["post"]["responses"]) >= {"201", "401", "403", "404", "409"}
    assert set(paths["/v2/user-reports/{association_id}/publication/versions"]) == {
        "post"
    }

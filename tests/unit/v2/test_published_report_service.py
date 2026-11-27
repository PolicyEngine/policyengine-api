"""Publishing a saved report, and reading it publicly, on SQLite's copy of the schema.

An author publishes one of their saved reports, showing one succeeded run of
its report; the page has a summary, authors, tags and content of its own,
and moves to newer runs as versions. Anyone reads the published page by the
saved report's ID, with the run of its newest version, or of an earlier one
when the author shows past versions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from policyengine_api.data.v2.models import ReportRunStatus
from policyengine_api.services.v2.published_reports.types import (
    PublicationCreateInput,
    PublicationUpdateInput,
    PublicationVersionInput,
)
from policyengine_api.services.v2.published_reports.validators import (
    PublicationExistsError,
    PublicationNotFoundError,
    PublicationRunAlreadyShownError,
    PublicationRunNotFoundError,
    PublicationRunNotSucceededError,
    PublishedReportNotFoundError,
    PublishedVersionNotFoundError,
    UnpublishableUserReportError,
)
from policyengine_api.services.v2.user_reports.database_session import (
    UserReportDatabaseSession,
)
from policyengine_api.services.v2.user_reports.services import V2UserReportService
from policyengine_api.services.v2.user_reports.types import UserReportUpdateInput
from policyengine_api.services.v2.user_reports.validators import (
    PublishedUserReportRepointError,
    UserReportNotFoundError,
)
from tests.fixtures.database_sessions import sqlite_v2_sessions
from tests.unit.v2.published_report_support import (
    PROVISIONS,
    RecordingReportReader,
    author_principal,
    publication_body,
    published_report_service,
    store_budget_window_run,
    store_report,
    store_report_run,
    store_saved_report,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

    from policyengine_api.services.v2.published_reports.services import (
        V2PublishedReportService,
    )
    from policyengine_api.services.v2.published_reports.types import PublicationRead
    from tests.unit.v2.published_report_support import SavedReportRows


@pytest.fixture
def sessions() -> Iterator[sessionmaker[Session]]:
    with sqlite_v2_sessions() as session_factory:
        yield session_factory


def _publish(
    service: V2PublishedReportService,
    saved: SavedReportRows,
    run_id: UUID,
    **changes: object,
) -> PublicationRead:
    return service.publish_report(
        principal=saved.principal,
        country_id="us",
        user_report_id=saved.user_report_id,
        publication_input=PublicationCreateInput.model_validate(
            publication_body(run_id, **changes)
        ),
    )


def _saved_report_with_run(
    sessions: sessionmaker[Session], **saved_report_columns: object
) -> tuple[SavedReportRows, UUID]:
    with sessions.begin() as session:
        saved = store_saved_report(session, **saved_report_columns)
        assert saved.report_id is not None
        run_id = store_report_run(session, saved.report_id)
    return saved, run_id


def _add_newer_run(
    sessions: sessionmaker[Session],
    saved: SavedReportRows,
    *,
    status: ReportRunStatus = ReportRunStatus.SUCCEEDED,
) -> UUID:
    assert saved.report_id is not None
    with sessions.begin() as session:
        return store_report_run(session, saved.report_id, status=status, days_later=1)


def _move(
    service: V2PublishedReportService, saved: SavedReportRows, run_id: UUID
) -> PublicationRead:
    return service.add_publication_version(
        principal=saved.principal,
        country_id="us",
        user_report_id=saved.user_report_id,
        version_input=PublicationVersionInput(run_id=run_id),
    )


def test_an_author_publishes_a_succeeded_run_of_their_saved_report(sessions) -> None:
    saved, run_id = _saved_report_with_run(sessions)
    service = published_report_service(sessions)

    publication = _publish(service, saved, run_id)

    assert publication.user_report_id == saved.user_report_id
    assert publication.country_id == "us"
    assert publication.summary == "What a larger child tax credit costs and who gains."
    assert publication.author_ids == ["nikhil-woodruff"]
    assert publication.tags == ["us", "child-tax-credit"]
    assert publication.content == [
        {"type": "markdown", "markdown": "## Why this reform"},
        {"type": "output", "output": "budgetary_impact"},
        {"type": "output", "output": "poverty_impact"},
    ]
    assert publication.show_past_versions is False
    assert [
        (version.run_id, version.country_package_version, version.policyengine_version)
        for version in publication.versions
    ] == [(run_id, "1.5.0", "4.2.0")]
    assert publication.versions[0].published_at == publication.published_at
    assert (
        service.get_publication(
            principal=saved.principal,
            country_id="us",
            user_report_id=saved.user_report_id,
        )
        == publication
    )


def test_a_budget_window_is_published_with_its_budget_window_run(sessions) -> None:
    with sessions.begin() as session:
        report_id = store_report(session, budget_window_size=10)
        saved = store_saved_report(session, report_id=report_id)
        window_run_id = store_budget_window_run(session, report_id)
    service = published_report_service(sessions)

    publication = _publish(service, saved, window_run_id)

    assert [version.run_id for version in publication.versions] == [window_run_id]
    assert publication.versions[0].policyengine_version == "4.2.0"


def test_a_budget_windows_year_is_not_one_of_its_runs_to_publish(sessions) -> None:
    with sessions.begin() as session:
        report_id = store_report(session, budget_window_size=10)
        saved = store_saved_report(session, report_id=report_id)
        window_run_id = store_budget_window_run(session, report_id)
        year_run_id = store_report_run(
            session, report_id, budget_window_run_id=window_run_id, days_later=1
        )

    with pytest.raises(PublicationRunNotFoundError):
        _publish(published_report_service(sessions), saved, year_run_id)


def test_a_run_of_another_report_is_refused(sessions) -> None:
    saved, _run_id = _saved_report_with_run(sessions)
    with sessions.begin() as session:
        other_run_id = store_report_run(session, store_report(session))

    with pytest.raises(PublicationRunNotFoundError):
        _publish(published_report_service(sessions), saved, other_run_id)


@pytest.mark.parametrize(
    "status",
    [ReportRunStatus.PENDING, ReportRunStatus.RUNNING, ReportRunStatus.FAILED],
)
def test_a_run_that_has_not_succeeded_is_refused(sessions, status) -> None:
    with sessions.begin() as session:
        saved = store_saved_report(session)
        assert saved.report_id is not None
        run_id = store_report_run(session, saved.report_id, status=status)

    with pytest.raises(PublicationRunNotSucceededError):
        _publish(published_report_service(sessions), saved, run_id)


def test_a_saved_report_naming_only_a_v1_report_cannot_be_published(sessions) -> None:
    with sessions.begin() as session:
        saved = store_saved_report(session, legacy_report_id=615)

    with pytest.raises(UnpublishableUserReportError, match="v1 report"):
        _publish(published_report_service(sessions), saved, uuid4())


def test_a_saved_report_without_a_name_cannot_be_published(sessions) -> None:
    saved, run_id = _saved_report_with_run(sessions, name=None)

    with pytest.raises(UnpublishableUserReportError, match="name"):
        _publish(published_report_service(sessions), saved, run_id)


def test_another_users_saved_report_is_not_found(sessions) -> None:
    saved, run_id = _saved_report_with_run(sessions)
    service = published_report_service(sessions)

    with pytest.raises(UserReportNotFoundError):
        service.publish_report(
            principal=author_principal(),
            country_id="us",
            user_report_id=saved.user_report_id,
            publication_input=PublicationCreateInput.model_validate(
                publication_body(run_id)
            ),
        )
    with pytest.raises(UserReportNotFoundError):
        service.publish_report(
            principal=saved.principal,
            country_id="uk",
            user_report_id=saved.user_report_id,
            publication_input=PublicationCreateInput.model_validate(
                publication_body(run_id)
            ),
        )


def test_a_saved_report_is_published_once(sessions) -> None:
    saved, run_id = _saved_report_with_run(sessions)
    service = published_report_service(sessions)
    _publish(service, saved, run_id)

    with pytest.raises(PublicationExistsError):
        _publish(service, saved, run_id)


def test_the_author_edits_the_fields_sent_and_keeps_the_others(sessions) -> None:
    saved, run_id = _saved_report_with_run(sessions)
    service = published_report_service(sessions)
    published = _publish(service, saved, run_id)

    edited = service.update_publication(
        principal=saved.principal,
        country_id="us",
        user_report_id=saved.user_report_id,
        publication_input=PublicationUpdateInput.model_validate(
            {
                "summary": "A shorter summary.",
                "content": [{"type": "output", "output": "budgetary_impact"}],
                "show_past_versions": True,
            }
        ),
    )

    assert edited.summary == "A shorter summary."
    assert edited.content == [{"type": "output", "output": "budgetary_impact"}]
    assert edited.show_past_versions is True
    assert edited.author_ids == published.author_ids
    assert edited.tags == published.tags
    assert edited.versions == published.versions
    assert edited.published_at == published.published_at


def test_editing_or_moving_an_unpublished_report_is_not_found(sessions) -> None:
    saved, run_id = _saved_report_with_run(sessions)
    service = published_report_service(sessions)

    with pytest.raises(PublicationNotFoundError):
        service.update_publication(
            principal=saved.principal,
            country_id="us",
            user_report_id=saved.user_report_id,
            publication_input=PublicationUpdateInput.model_validate({"tags": []}),
        )
    with pytest.raises(PublicationNotFoundError):
        _move(service, saved, run_id)
    with pytest.raises(PublicationNotFoundError):
        service.get_publication(
            principal=saved.principal,
            country_id="us",
            user_report_id=saved.user_report_id,
        )


def test_moving_to_a_newer_run_adds_a_version_newest_first(sessions) -> None:
    saved, run_id = _saved_report_with_run(sessions)
    service = published_report_service(sessions)
    published = _publish(service, saved, run_id)
    newer_run_id = _add_newer_run(sessions, saved)

    moved = _move(service, saved, newer_run_id)

    assert [
        (version.run_id, version.policyengine_version) for version in moved.versions
    ] == [(newer_run_id, "4.3.0"), (run_id, "4.2.0")]
    assert moved.versions[1] == published.versions[0]
    assert moved.updated_at >= published.updated_at
    assert moved.content == published.content


def test_moving_to_a_run_the_page_has_shown_is_refused(sessions) -> None:
    saved, run_id = _saved_report_with_run(sessions)
    service = published_report_service(sessions)
    _publish(service, saved, run_id)

    with pytest.raises(PublicationRunAlreadyShownError):
        _move(service, saved, run_id)


def test_moving_to_a_run_that_has_not_succeeded_is_refused(sessions) -> None:
    saved, run_id = _saved_report_with_run(sessions)
    service = published_report_service(sessions)
    _publish(service, saved, run_id)
    pending_run_id = _add_newer_run(sessions, saved, status=ReportRunStatus.PENDING)

    with pytest.raises(PublicationRunNotSucceededError):
        _move(service, saved, pending_run_id)


def test_withdrawing_removes_the_page_and_it_can_be_published_again(sessions) -> None:
    saved, run_id = _saved_report_with_run(sessions)
    service = published_report_service(sessions)
    _publish(service, saved, run_id)

    service.withdraw_publication(
        principal=saved.principal,
        country_id="us",
        user_report_id=saved.user_report_id,
    )

    with pytest.raises(PublicationNotFoundError):
        service.get_publication(
            principal=saved.principal,
            country_id="us",
            user_report_id=saved.user_report_id,
        )
    with pytest.raises(PublishedReportNotFoundError):
        service.get_published_report(
            country_id="us", user_report_id=saved.user_report_id
        )
    with pytest.raises(PublicationNotFoundError):
        service.withdraw_publication(
            principal=saved.principal,
            country_id="us",
            user_report_id=saved.user_report_id,
        )
    republished = _publish(service, saved, run_id)
    assert [version.run_id for version in republished.versions] == [run_id]


def test_only_the_owner_withdraws_a_page(sessions) -> None:
    saved, run_id = _saved_report_with_run(sessions)
    service = published_report_service(sessions)
    _publish(service, saved, run_id)

    with pytest.raises(UserReportNotFoundError):
        service.withdraw_publication(
            principal=author_principal(),
            country_id="us",
            user_report_id=saved.user_report_id,
        )
    assert service.get_published_report(
        country_id="us", user_report_id=saved.user_report_id
    )


def test_anyone_reads_the_page_with_its_newest_run_and_no_owner(sessions) -> None:
    saved, run_id = _saved_report_with_run(sessions, baseline_reform_name="Plan A")
    reports = RecordingReportReader()
    service = published_report_service(sessions, reports)
    published = _publish(service, saved, run_id)

    page = service.get_published_report(
        country_id="us", user_report_id=saved.user_report_id
    )

    assert page.id == saved.user_report_id
    assert page.country_id == "us"
    assert page.title == "Expanded child tax credit"
    assert page.summary == published.summary
    assert page.author_ids == published.author_ids
    assert page.tags == published.tags
    assert page.content == published.content
    assert page.show_past_versions is False
    assert page.saved_report.source_note == "From the chat"
    assert page.saved_report.provisions == PROVISIONS
    assert page.saved_report.budget_window_years is None
    assert page.saved_report.baseline_reform is not None
    assert page.saved_report.baseline_reform.name == "Plan A"
    assert page.version == published.versions[0]
    assert page.versions == published.versions
    assert page.published_at == published.published_at
    assert reports.calls == [
        {
            "country_id": "us",
            "report_id": saved.report_id,
            "run_id": run_id,
            "requester": None,
        }
    ]
    # The report reads with the saved report's name and none of its notes.
    assert page.report.label == "Expanded child tax credit"
    assert page.report.description is None
    assert page.report.run is not None
    assert page.report.run.id == run_id


def test_past_versions_are_readable_only_while_the_author_shows_them(sessions) -> None:
    saved, run_id = _saved_report_with_run(sessions)
    reports = RecordingReportReader()
    service = published_report_service(sessions, reports)
    first_version = _publish(service, saved, run_id).versions[0]
    newer_run_id = _add_newer_run(sessions, saved)
    moved = _move(service, saved, newer_run_id)

    hidden = service.get_published_report(
        country_id="us", user_report_id=saved.user_report_id
    )
    with pytest.raises(PublishedVersionNotFoundError):
        service.get_published_report(
            country_id="us",
            user_report_id=saved.user_report_id,
            version_id=first_version.id,
        )
    service.update_publication(
        principal=saved.principal,
        country_id="us",
        user_report_id=saved.user_report_id,
        publication_input=PublicationUpdateInput(show_past_versions=True),
    )
    past = service.get_published_report(
        country_id="us",
        user_report_id=saved.user_report_id,
        version_id=first_version.id,
    )

    assert hidden.version.run_id == newer_run_id
    assert hidden.versions == (moved.versions[0],)
    assert past.version == first_version
    assert past.versions == moved.versions
    assert past.report.run is not None
    assert past.report.run.id == run_id
    assert [call["run_id"] for call in reports.calls] == [newer_run_id, run_id]


def test_the_newest_version_is_readable_by_its_id(sessions) -> None:
    saved, run_id = _saved_report_with_run(sessions)
    service = published_report_service(sessions)
    newest = _publish(service, saved, run_id).versions[0]

    page = service.get_published_report(
        country_id="us", user_report_id=saved.user_report_id, version_id=newest.id
    )

    assert page.version == newest


def test_a_version_of_no_page_is_not_found(sessions) -> None:
    saved, run_id = _saved_report_with_run(sessions)
    service = published_report_service(sessions)
    _publish(service, saved, run_id, show_past_versions=True)

    with pytest.raises(PublishedVersionNotFoundError):
        service.get_published_report(
            country_id="us", user_report_id=saved.user_report_id, version_id=uuid4()
        )


def test_an_unpublished_or_other_countrys_page_is_not_found(sessions) -> None:
    saved, run_id = _saved_report_with_run(sessions)
    service = published_report_service(sessions)

    with pytest.raises(PublishedReportNotFoundError):
        service.get_published_report(
            country_id="us", user_report_id=saved.user_report_id
        )
    _publish(service, saved, run_id)
    with pytest.raises(PublishedReportNotFoundError):
        service.get_published_report(
            country_id="uk", user_report_id=saved.user_report_id
        )


def test_a_published_saved_report_cannot_be_repointed(sessions) -> None:
    saved, run_id = _saved_report_with_run(sessions)
    _publish(published_report_service(sessions), saved, run_id)
    with sessions.begin() as session:
        other_report_id = store_report(session)
    user_reports = V2UserReportService(UserReportDatabaseSession(sessions))

    with pytest.raises(PublishedUserReportRepointError):
        user_reports.patch_user_report(
            principal=saved.principal,
            country_id="us",
            association_id=saved.user_report_id,
            association_input=UserReportUpdateInput(report_id=other_report_id),
        )
    renamed = user_reports.patch_user_report(
        principal=saved.principal,
        country_id="us",
        association_id=saved.user_report_id,
        association_input=UserReportUpdateInput(
            name="A new title", report_id=saved.report_id
        ),
    )

    assert renamed.name == "A new title"
    assert renamed.report_id == saved.report_id


def test_an_unpublished_saved_report_can_be_repointed(sessions) -> None:
    saved, _run_id = _saved_report_with_run(sessions)
    with sessions.begin() as session:
        other_report_id = store_report(session)

    repointed = V2UserReportService(
        UserReportDatabaseSession(sessions)
    ).patch_user_report(
        principal=saved.principal,
        country_id="us",
        association_id=saved.user_report_id,
        association_input=UserReportUpdateInput(report_id=other_report_id),
    )

    assert repointed.report_id == other_report_id

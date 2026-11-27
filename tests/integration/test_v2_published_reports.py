"""Published reports on migrated PostgreSQL, written and read as API v1's runtime role.

An author publishes a saved report showing one succeeded run of its report,
moves the page to newer runs as versions and withdraws it; anyone reads it.
The database deletes a published report with its saved report, and so with
its owner's account, refuses to repoint a published saved report to another
report, and keeps every run a page has shown. The revision before this one
has none of the published-report tables.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import col

from policyengine_api.data.v2.models import (
    PublishedReport,
    PublishedReportVersion,
    ReportRun,
    User,
    UserReportAssociation,
)
from policyengine_api.services.v2.published_reports.database_session import (
    PublishedReportDatabaseSession,
)
from policyengine_api.services.v2.published_reports.services import (
    V2PublishedReportService,
)
from policyengine_api.services.v2.published_reports.types import (
    PublicationCreateInput,
    PublicationUpdateInput,
    PublicationVersionInput,
)
from policyengine_api.services.v2.stored_reports.database_session import (
    StoredReportDatabaseSession,
)
from policyengine_api.services.v2.stored_reports.services import V2StoredReportService
from policyengine_api.services.v2.user_reports.database_session import (
    UserReportDatabaseSession,
)
from policyengine_api.services.v2.user_reports.services import V2UserReportService
from policyengine_api.services.v2.user_reports.types import UserReportUpdateInput
from tests.fixtures.database_sessions import recorded_statements, schema_inspector
from tests.fixtures.economy_results import us_economy_result
from tests.fixtures.integration.alembic_v2 import alembic_v2_config
from tests.integration.simulation_rows import add_row, refused
from tests.integration.stored_report_rows import (
    STARTED_AT,
    BudgetWindowYear,
    RunSettings,
    delete_catalog,
    store_budget_window_run,
    store_catalog,
    store_report,
    store_report_run,
)
from tests.integration.user_report_run_support import (
    CURRENT_VERSIONS,
    current_versions,
    store_signed_in_user,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

    from policyengine_api.services.v2.identity.types import UserPrincipal
    from tests.integration.conftest import ManagedV2Roles
    from tests.integration.stored_report_rows import CatalogRows, StoredReport

# The revision before the published-report tables: dropping dynamic_id.
PREVIOUS_REVISION = "1c651058fac5"
NEWER_VERSIONS = {**CURRENT_VERSIONS, "policyengine_version": "4.3.0"}
PUBLISHED_TABLES = ("published_reports", "published_report_versions")
PUBLISHED_REPORT_KEY = "fk_published_reports_user_report_report"


@pytest.fixture
def owner_sessions(
    v2_owner_sessions: sessionmaker[Session],
) -> Iterator[sessionmaker[Session]]:
    """Yield the owner's Session factories on a database at head; leave it at head."""
    command.upgrade(alembic_v2_config(), "head")
    try:
        yield v2_owner_sessions
    finally:
        command.upgrade(alembic_v2_config(), "head")


@pytest.fixture
def catalog(owner_sessions: sessionmaker[Session]) -> Iterator[CatalogRows]:
    with owner_sessions.begin() as session:
        stored = store_catalog(session, "us")
    yield stored
    with owner_sessions.begin() as session:
        session.execute(
            delete(UserReportAssociation).where(
                col(UserReportAssociation.report_id).in_(stored.report_ids)
            )
        )
        delete_catalog(session, stored)


@pytest.fixture
def runtime_sessions(
    managed_v2_roles: ManagedV2Roles,
    v2_sessions_as_role: Callable[[str], sessionmaker[Session]],
) -> sessionmaker[Session]:
    return v2_sessions_as_role(managed_v2_roles.runtime)


@pytest.fixture
def author(
    runtime_sessions: sessionmaker[Session], owner_sessions: sessionmaker[Session]
) -> Iterator[tuple[UserPrincipal, UUID]]:
    principal, user_id = store_signed_in_user(
        runtime_sessions, owner_sessions, user_type="author"
    )
    yield principal, user_id
    with owner_sessions.begin() as session:
        session.execute(delete(User).where(col(User.id) == user_id))


def _service(sessions: sessionmaker[Session]) -> V2PublishedReportService:
    return V2PublishedReportService(
        PublishedReportDatabaseSession(sessions),
        reports=V2StoredReportService(
            StoredReportDatabaseSession(sessions), current_versions=current_versions
        ),
    )


def _store_run(
    session: Session,
    catalog: CatalogRows,
    report: StoredReport,
    *,
    days_later: int = 0,
    versions: dict[str, str] = CURRENT_VERSIONS,
) -> UUID:
    return store_report_run(
        session,
        catalog,
        report,
        RunSettings(
            versions=versions,
            status="succeeded",
            created_at=STARTED_AT + timedelta(days=days_later),
        ),
        result=us_economy_result(),
    ).report_run_id


def _saved_report(session: Session, *, user_id: UUID, report_id: UUID) -> UUID:
    saved_report_id = uuid4()
    add_row(
        session,
        UserReportAssociation,
        id=saved_report_id,
        user_id=user_id,
        report_id=report_id,
        country_id="us",
        name="Expanded child tax credit",
        description="My own notes",
    )
    return saved_report_id


def _publication_input(run_id: UUID) -> PublicationCreateInput:
    return PublicationCreateInput.model_validate(
        {
            "run_id": str(run_id),
            "summary": "What a larger child tax credit costs.",
            "author_ids": ["nikhil-woodruff"],
            "tags": ["us"],
            "content": [{"type": "output", "output": "budgetary_impact"}],
        }
    )


def _row_counts(
    owner_sessions: sessionmaker[Session], user_report_id: UUID
) -> tuple[int, int]:
    with owner_sessions() as session:
        pages = session.scalar(
            select(func.count())
            .select_from(PublishedReport)
            .where(col(PublishedReport.user_report_id) == user_report_id)
        )
        versions = session.scalar(
            select(func.count())
            .select_from(PublishedReportVersion)
            .where(col(PublishedReportVersion.user_report_id) == user_report_id)
        )
    return int(pages or 0), int(versions or 0)


@pytest.fixture
def published(
    owner_sessions: sessionmaker[Session],
    runtime_sessions: sessionmaker[Session],
    catalog: CatalogRows,
    author: tuple[UserPrincipal, UUID],
) -> dict[str, Any]:
    """Publish an author's saved report as the runtime role, with one run of it."""
    principal, user_id = author
    with owner_sessions.begin() as session:
        report = store_report(session, catalog)
        run_id = _store_run(session, catalog, report)
        newer_run_id = _store_run(
            session, catalog, report, days_later=1, versions=NEWER_VERSIONS
        )
        user_report_id = _saved_report(
            session, user_id=user_id, report_id=report.report_id
        )
    _service(runtime_sessions).publish_report(
        principal=principal,
        country_id="us",
        user_report_id=user_report_id,
        publication_input=_publication_input(run_id),
    )
    return {
        "principal": principal,
        "user_id": user_id,
        "report": report,
        "run_id": run_id,
        "newer_run_id": newer_run_id,
        "user_report_id": user_report_id,
    }


def test_an_author_publishes_moves_and_withdraws_a_page(
    owner_sessions: sessionmaker[Session],
    runtime_sessions: sessionmaker[Session],
    published: dict[str, Any],
) -> None:
    service = _service(runtime_sessions)
    principal = published["principal"]
    user_report_id = published["user_report_id"]

    first = service.get_published_report(country_id="us", user_report_id=user_report_id)
    moved = service.add_publication_version(
        principal=principal,
        country_id="us",
        user_report_id=user_report_id,
        version_input=PublicationVersionInput(run_id=published["newer_run_id"]),
    )
    service.update_publication(
        principal=principal,
        country_id="us",
        user_report_id=user_report_id,
        publication_input=PublicationUpdateInput(show_past_versions=True),
    )
    newest = service.get_published_report(
        country_id="us", user_report_id=user_report_id
    )
    past = service.get_published_report(
        country_id="us",
        user_report_id=user_report_id,
        version_id=moved.versions[1].id,
    )
    service.withdraw_publication(
        principal=principal, country_id="us", user_report_id=user_report_id
    )

    assert first.title == "Expanded child tax credit"
    assert first.report.label == "Expanded child tax credit"
    assert first.report.description is None
    assert first.report.run is not None
    assert first.report.run.id == published["run_id"]
    assert first.report.result is not None
    assert [version.policyengine_version for version in moved.versions] == [
        "4.3.0",
        "4.2.0",
    ]
    assert newest.report.run is not None
    assert newest.report.run.id == published["newer_run_id"]
    assert past.report.run is not None
    assert past.report.run.id == published["run_id"]
    assert [version.run_id for version in past.versions] == [
        published["newer_run_id"],
        published["run_id"],
    ]
    assert _row_counts(owner_sessions, user_report_id) == (0, 0)


def test_deleting_the_saved_report_deletes_its_page(
    owner_sessions: sessionmaker[Session],
    runtime_sessions: sessionmaker[Session],
    published: dict[str, Any],
) -> None:
    V2UserReportService(UserReportDatabaseSession(runtime_sessions)).delete_user_report(
        principal=published["principal"],
        country_id="us",
        association_id=published["user_report_id"],
    )

    assert _row_counts(owner_sessions, published["user_report_id"]) == (0, 0)


def test_deleting_the_account_deletes_its_page(
    owner_sessions: sessionmaker[Session],
    runtime_sessions: sessionmaker[Session],
    published: dict[str, Any],
) -> None:
    # As the account deletion's connector deletes the user.
    with runtime_sessions.begin() as session:
        session.execute(delete(User).where(col(User.id) == published["user_id"]))

    assert _row_counts(owner_sessions, published["user_report_id"]) == (0, 0)


def test_the_database_refuses_to_repoint_a_published_saved_report(
    owner_sessions: sessionmaker[Session],
    runtime_sessions: sessionmaker[Session],
    catalog: CatalogRows,
    published: dict[str, Any],
) -> None:
    with owner_sessions.begin() as session:
        other_report_id = store_report(session, catalog).report_id

    with (
        runtime_sessions.begin() as session,
        refused(session, IntegrityError, match=PUBLISHED_REPORT_KEY),
    ):
        session.execute(
            update(UserReportAssociation)
            .where(col(UserReportAssociation.id) == published["user_report_id"])
            .values(report_id=other_report_id)
        )
    with (
        runtime_sessions.begin() as session,
        refused(session, IntegrityError, match=PUBLISHED_REPORT_KEY),
    ):
        session.execute(
            update(UserReportAssociation)
            .where(col(UserReportAssociation.id) == published["user_report_id"])
            .values(report_id=None, legacy_report_id=615)
        )
    with runtime_sessions.begin() as session:
        session.execute(
            update(UserReportAssociation)
            .where(col(UserReportAssociation.id) == published["user_report_id"])
            .values(name="A new title")
        )
    assert _row_counts(owner_sessions, published["user_report_id"]) == (1, 1)


def test_a_run_a_page_has_shown_cannot_be_deleted(
    owner_sessions: sessionmaker[Session], published: dict[str, Any]
) -> None:
    with (
        owner_sessions.begin() as session,
        refused(
            session,
            IntegrityError,
            match="fk_published_report_versions_report_run_id_report_runs",
        ),
    ):
        session.execute(
            delete(ReportRun).where(col(ReportRun.id) == published["run_id"])
        )

    with owner_sessions() as session:
        assert session.get(ReportRun, published["run_id"]) is not None


def test_a_second_page_or_a_second_version_of_one_run_is_refused(
    owner_sessions: sessionmaker[Session], published: dict[str, Any]
) -> None:
    """Two publishes or moves at once: the database's keys refuse the second."""
    with (
        owner_sessions.begin() as session,
        refused(session, IntegrityError, match="pk_published_reports"),
    ):
        add_row(
            session,
            PublishedReport,
            user_report_id=published["user_report_id"],
            report_id=published["report"].report_id,
            summary="A second page",
            author_ids=["nikhil-woodruff"],
            tags=[],
            content=[],
        )
    with (
        owner_sessions.begin() as session,
        refused(
            session,
            IntegrityError,
            match="uq_published_report_versions_user_report_id_report_run_id",
        ),
    ):
        add_row(
            session,
            PublishedReportVersion,
            id=uuid4(),
            user_report_id=published["user_report_id"],
            report_run_id=published["run_id"],
        )

    assert _row_counts(owner_sessions, published["user_report_id"]) == (1, 1)


@pytest.mark.parametrize("runs", ["none", "both"])
def test_a_version_names_exactly_one_run(
    owner_sessions: sessionmaker[Session],
    catalog: CatalogRows,
    published: dict[str, Any],
    runs: str,
) -> None:
    with owner_sessions.begin() as session:
        window_run_id = store_budget_window_run(
            session,
            catalog,
            published["report"],
            RunSettings(
                versions=CURRENT_VERSIONS, status="succeeded", created_at=STARTED_AT
            ),
        )
    with (
        owner_sessions.begin() as session,
        refused(session, IntegrityError, match="ck_published_report_versions_one_run"),
    ):
        add_row(
            session,
            PublishedReportVersion,
            id=uuid4(),
            user_report_id=published["user_report_id"],
            report_run_id=None if runs == "none" else published["newer_run_id"],
            budget_window_run_id=None if runs == "none" else window_run_id,
        )


def test_the_previous_revision_has_no_published_report_tables(
    owner_sessions: sessionmaker[Session],
) -> None:
    command.downgrade(alembic_v2_config(), PREVIOUS_REVISION)
    with owner_sessions() as session:
        inspector = schema_inspector(session)
        downgraded_tables = set(inspector.get_table_names())
        downgraded_unique = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints(
                "user_report_associations"
            )
        }
    command.upgrade(alembic_v2_config(), "head")
    with owner_sessions() as session:
        inspector = schema_inspector(session)
        upgraded_tables = set(inspector.get_table_names())
        upgraded_unique = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints(
                "user_report_associations"
            )
        }
        foreign_keys = {
            key["name"]: (
                key["options"].get("ondelete"),
                key["options"].get("onupdate"),
            )
            for key in inspector.get_foreign_keys("published_reports")
        }

    assert downgraded_tables.isdisjoint(PUBLISHED_TABLES)
    assert "uq_user_report_associations_id_report_id" not in downgraded_unique
    assert set(PUBLISHED_TABLES) <= upgraded_tables
    assert "uq_user_report_associations_id_report_id" in upgraded_unique
    assert foreign_keys == {
        "fk_published_reports_user_report_report": ("CASCADE", "RESTRICT")
    }


def _locks(statements: list[str], table: str) -> bool:
    """Return whether a statement selected from ``table`` FOR UPDATE."""
    return any(
        statement.lstrip().upper().startswith("SELECT")
        and f"FROM {table}" in statement
        and "FOR UPDATE" in statement
        for statement in statements
    )


def test_writes_lock_the_rows_they_check(
    runtime_sessions: sessionmaker[Session], published: dict[str, Any]
) -> None:
    """Each write locks what it checks, so a concurrent write waits for it.

    A publish and a saved report's edit lock the saved report, so a name
    can't be cleared while a publish reads it; an edit, a move and a
    withdrawal lock the page, so none of them runs on a page another has
    just withdrawn.
    """
    service = _service(runtime_sessions)
    principal = published["principal"]
    user_report_id = published["user_report_id"]
    owner_operations = {
        "edit": lambda: service.update_publication(
            principal=principal,
            country_id="us",
            user_report_id=user_report_id,
            publication_input=PublicationUpdateInput(show_past_versions=True),
        ),
        "move": lambda: service.add_publication_version(
            principal=principal,
            country_id="us",
            user_report_id=user_report_id,
            version_input=PublicationVersionInput(run_id=published["newer_run_id"]),
        ),
        "withdraw": lambda: service.withdraw_publication(
            principal=principal, country_id="us", user_report_id=user_report_id
        ),
        "publish": lambda: service.publish_report(
            principal=principal,
            country_id="us",
            user_report_id=user_report_id,
            publication_input=_publication_input(published["run_id"]),
        ),
        "rename": lambda: V2UserReportService(
            UserReportDatabaseSession(runtime_sessions)
        ).patch_user_report(
            principal=principal,
            country_id="us",
            association_id=user_report_id,
            association_input=UserReportUpdateInput(name="A new title"),
        ),
    }
    locked: dict[str, tuple[bool, bool]] = {}
    for name, operation in owner_operations.items():
        with recorded_statements(runtime_sessions) as statements:
            operation()
        locked[name] = (
            _locks(statements, "published_reports"),
            _locks(statements, "user_report_associations"),
        )

    assert locked == {
        "edit": (True, False),
        "move": (True, False),
        "withdraw": (True, False),
        "publish": (False, True),
        "rename": (False, True),
    }


def test_a_budget_window_is_published_with_its_window_run(
    owner_sessions: sessionmaker[Session],
    runtime_sessions: sessionmaker[Session],
    catalog: CatalogRows,
    author: tuple[UserPrincipal, UUID],
) -> None:
    principal, user_id = author
    succeeded = RunSettings(
        versions=CURRENT_VERSIONS, status="succeeded", created_at=STARTED_AT
    )
    with owner_sessions.begin() as session:
        window = store_report(session, catalog, budget_window_size=2)
        window_run_id = store_budget_window_run(session, catalog, window, succeeded)
        for year in (2026, 2027):
            store_report_run(
                session,
                catalog,
                window,
                replace(
                    succeeded,
                    budget_window_year=BudgetWindowYear(
                        budget_window_run_id=window_run_id, year=year
                    ),
                ),
            )
        user_report_id = _saved_report(
            session, user_id=user_id, report_id=window.report_id
        )

    publication = _service(runtime_sessions).publish_report(
        principal=principal,
        country_id="us",
        user_report_id=user_report_id,
        publication_input=_publication_input(window_run_id),
    )

    assert [
        (version.run_id, version.policyengine_version)
        for version in publication.versions
    ] == [(window_run_id, CURRENT_VERSIONS["policyengine_version"])]
    with (
        owner_sessions.begin() as session,
        refused(
            session,
            IntegrityError,
            match="uq_published_report_versions_user_report_window_run",
        ),
    ):
        add_row(
            session,
            PublishedReportVersion,
            id=uuid4(),
            user_report_id=user_report_id,
            budget_window_run_id=window_run_id,
        )

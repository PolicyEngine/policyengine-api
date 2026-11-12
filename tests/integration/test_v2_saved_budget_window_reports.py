"""Save budget-window reports in migrated PostgreSQL.

The saved-report service runs as the Public API's runtime role. A saved
report naming a detailed-save report gives that report's budget window as
``budget_window_years``, read from ``reports.budget_window_size`` in the
write's transaction, or none for a report without a window of two or more
years.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel import Session

from policyengine_api.constants import REPO
from policyengine_api.data.v2.models import User
from policyengine_api.services.v2.identity.types import UnauthenticatedPrincipal
from policyengine_api.services.v2.user_reports.database_session import (
    UserReportDatabaseSession,
)
from policyengine_api.services.v2.user_reports.services import V2UserReportService
from policyengine_api.services.v2.user_reports.types import (
    UserReportCreateFields,
    UserReportUpdateInput,
)
from policyengine_api.services.v2.user_reports.validators import (
    AssociationBudgetWindowConflictError,
)
from tests.integration.stored_report_rows import (
    BudgetWindowYear,
    RunSettings,
    delete_catalog,
    store_budget_window_run,
    store_catalog,
    store_report,
    store_report_run,
)
from tests.unit.v2.user_service_support import default_legacy_references

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID

    from sqlalchemy import Engine

    from tests.integration.stored_report_rows import CatalogRows


@pytest.fixture
def owner_engine(disposable_v2_database_url: str) -> Iterator[Engine]:
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def browsers(owner_engine: Engine) -> Iterator[list[UUID]]:
    """Signed-out browsers' user IDs; their users and saved records go afterwards."""
    user_ids: list[UUID] = []
    yield user_ids
    with owner_engine.begin() as connection:
        connection.execute(delete(User).where(User.id.in_(user_ids)))


@pytest.fixture
def catalog(owner_engine: Engine, browsers: list[UUID]) -> Iterator[CatalogRows]:
    """Store a US catalog; delete it after the saved records that name its reports."""
    with owner_engine.begin() as connection:
        stored = store_catalog(connection, "us")
    yield stored
    with owner_engine.begin() as connection:
        connection.execute(delete(User).where(User.id.in_(browsers)))
        delete_catalog(connection, stored)


@pytest.fixture
def service(managed_v2_roles, v2_engine_as_role) -> Iterator[V2UserReportService]:
    engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    yield V2UserReportService(
        UserReportDatabaseSession(sessions), default_legacy_references()
    )
    engine.dispose()


def browser(browsers: list[UUID]) -> UnauthenticatedPrincipal:
    user_id = uuid4()
    browsers.append(user_id)
    return UnauthenticatedPrincipal(user_id=user_id)


def save(
    service: V2UserReportService,
    principal: UnauthenticatedPrincipal,
    **fields: Any,
) -> Any:
    return service.create_user_report(
        principal=principal,
        association_input=UserReportCreateFields(country_id="us", **fields),
    )


def test_a_saved_budget_window_gives_the_reports_window(
    owner_engine: Engine,
    catalog: CatalogRows,
    browsers: list[UUID],
    service: V2UserReportService,
) -> None:
    with owner_engine.begin() as connection:
        window = store_report(connection, catalog, budget_window_size=10)
        one_year = store_report(connection, catalog, budget_window_size=1)
        economy = store_report(connection, catalog)
    principal = browser(browsers)

    saved = [
        save(service, principal, report_id=window.report_id, budget_window_years=10),
        save(service, principal, report_id=one_year.report_id),
        save(service, principal, report_id=economy.report_id),
    ]

    assert [record.budget_window_years for record in saved] == [10, None, None]


# The report's window size, then the saved report's budget_window_years.
DISAGREEING_WINDOWS = {
    "other-size": (10, 5),
    "no-years-for-a-window": (10, None),
    "years-for-an-economy-report": (None, 3),
}


@pytest.mark.parametrize(
    "window", list(DISAGREEING_WINDOWS.values()), ids=list(DISAGREEING_WINDOWS)
)
def test_a_saved_report_disagreeing_with_the_reports_window_is_refused(
    owner_engine: Engine,
    catalog: CatalogRows,
    browsers: list[UUID],
    service: V2UserReportService,
    window: tuple[int | None, int | None],
) -> None:
    budget_window_size, budget_window_years = window
    with owner_engine.begin() as connection:
        report = store_report(
            connection, catalog, budget_window_size=budget_window_size
        )

    with pytest.raises(
        AssociationBudgetWindowConflictError, match=str(report.report_id)
    ):
        save(
            service,
            browser(browsers),
            report_id=report.report_id,
            budget_window_years=budget_window_years,
        )


def test_an_update_keeps_the_saved_window_agreeing_with_its_report(
    owner_engine: Engine,
    catalog: CatalogRows,
    browsers: list[UUID],
    service: V2UserReportService,
) -> None:
    with owner_engine.begin() as connection:
        window = store_report(connection, catalog, budget_window_size=10)
        other_window = store_report(connection, catalog, budget_window_size=5)
        economy = store_report(connection, catalog)
    principal = browser(browsers)
    saved = save(service, principal, report_id=economy.report_id)

    def update(**change: Any) -> Any:
        return service.patch_user_report(
            principal=principal,
            country_id="us",
            association_id=saved.id,
            association_input=UserReportUpdateInput(**change),
        )

    repointed = update(report_id=window.report_id, budget_window_years=10)
    for change in (
        {"budget_window_years": 5},
        {"report_id": other_window.report_id},
        {"report_id": economy.report_id},
    ):
        with pytest.raises(AssociationBudgetWindowConflictError):
            update(**change)
    renamed = update(name="Ten years")
    moved = update(report_id=other_window.report_id, budget_window_years=5)

    assert repointed.budget_window_years == 10
    assert (renamed.name, renamed.budget_window_years) == ("Ten years", 10)
    assert (moved.report_id, moved.budget_window_years) == (other_window.report_id, 5)


def test_a_v1_saved_report_keeps_its_own_window(
    catalog: CatalogRows, browsers: list[UUID], service: V2UserReportService
) -> None:
    saved = save(
        service, browser(browsers), legacy_report_id=615, budget_window_years=10
    )

    assert saved.budget_window_years == 10


def test_a_succeeded_window_whose_result_cannot_be_read_can_still_be_saved(
    owner_engine: Engine,
    catalog: CatalogRows,
    browsers: list[UUID],
    service: V2UserReportService,
) -> None:
    # Saving reads only the report's window size, never its figures, so a
    # window whose years stored no result rows is saved like any other.
    versions = {"country_package_version": "1.5.0", "policyengine_version": "4.2.0"}
    with owner_engine.begin() as connection:
        window = store_report(connection, catalog, budget_window_size=2)
        window_run_id = store_budget_window_run(
            connection, catalog, window, RunSettings(versions=versions)
        )
        for year in (2026, 2027):
            store_report_run(
                connection,
                catalog,
                window,
                RunSettings(
                    versions=versions,
                    budget_window_year=BudgetWindowYear(
                        budget_window_run_id=window_run_id, year=year
                    ),
                ),
            )

    saved = save(
        service, browser(browsers), report_id=window.report_id, budget_window_years=2
    )

    assert (saved.report_id, saved.budget_window_years) == (window.report_id, 2)

"""What each user reads of a shared report, on migrated PostgreSQL.

C1 · 24's answers 7 and 6. A read without ``run_id`` answers the requesting
user's newest recorded run of the report, else its newest succeeded run that
wasn't forced, else its newest run that wasn't forced; a forced run is never
the default. A report's label and description are the requesting user's
saved report's name and description, and null without one. The routes run as
the Public API's runtime role.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel import Session

from policyengine_api.constants import REPO
from policyengine_api.libs.user_auth import UNAUTHENTICATED_USER_HEADER
from tests.fixtures.economy_results import us_economy_result
from tests.integration.stored_report_rows import (
    STARTED_AT,
    RunSettings,
    delete_catalog,
    store_catalog,
    store_report,
    store_report_run,
)
from tests.integration.user_report_run_support import (
    CURRENT_VERSIONS,
    JoinedRun,
    JoiningSimulationService,
    as_browser,
    client_for,
    store_saved_report,
    store_window,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Connection, Engine

    from tests.integration.stored_report_rows import CatalogRows, StoredReport

NEWER_VERSIONS = {**CURRENT_VERSIONS, "policyengine_version": "4.3.0"}


@pytest.fixture
def owner_engine(disposable_v2_database_url: str) -> Iterator[Engine]:
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    engine = create_engine(disposable_v2_database_url, poolclass=NullPool)
    yield engine
    engine.dispose()


@pytest.fixture
def catalog(owner_engine: Engine) -> Iterator[CatalogRows]:
    with owner_engine.begin() as connection:
        stored = store_catalog(connection, "us")
    yield stored
    with owner_engine.begin() as connection:
        delete_catalog(connection, stored)


@pytest.fixture
def runtime_sessions(managed_v2_roles, v2_engine_as_role) -> Iterator[Any]:
    engine = v2_engine_as_role(managed_v2_roles.runtime, poolclass=NullPool)
    yield sessionmaker(engine, class_=Session)
    engine.dispose()


@pytest.fixture
def browsers(owner_engine: Engine) -> Iterator[list[UUID]]:
    """Name signed-out browsers' users, and delete them and their records after."""
    browser_ids = [uuid4() for _ in range(2)]
    yield browser_ids
    with owner_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": browser_ids}
        )


def store_run(  # noqa: PLR0913  # each run differs in a keyword-only setting
    connection: Connection,
    catalog: CatalogRows,
    report: StoredReport,
    *,
    days_later: int,
    status: str,
    forced: bool = False,
    versions: dict[str, str] = CURRENT_VERSIONS,
) -> UUID:
    """Store a run of the report, with its result once it succeeded."""
    return store_report_run(
        connection,
        catalog,
        report,
        RunSettings(
            versions=versions,
            status=status,
            created_at=STARTED_AT + timedelta(days=days_later),
            forced=forced,
        ),
        result=us_economy_result() if status == "succeeded" else None,
    ).report_run_id


def read_item(client: Any, report_id: UUID, headers: dict[str, str] | None = None):
    response = client.get(f"/v2/reports/{report_id}?country_id=us", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["result"]["item"]


def test_without_a_record_the_newest_succeeded_unforced_run_is_read(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
        store_run(connection, catalog, report, days_later=0, status="failed")
        succeeded = store_run(
            connection, catalog, report, days_later=1, status="succeeded"
        )
        store_run(
            connection, catalog, report, days_later=2, status="succeeded", forced=True
        )
        store_run(
            connection,
            catalog,
            report,
            days_later=3,
            status="pending",
            versions=NEWER_VERSIONS,
        )
        only_forced = store_report(connection, catalog)
        store_run(
            connection,
            catalog,
            only_forced,
            days_later=0,
            status="succeeded",
            forced=True,
        )
        unsucceeded = store_report(connection, catalog)
        store_run(connection, catalog, unsucceeded, days_later=0, status="failed")
        newest_unforced = store_run(
            connection, catalog, unsucceeded, days_later=1, status="pending"
        )
    client = client_for(
        runtime_sessions, JoiningSimulationService(owner_engine, catalog)
    )

    item = read_item(client, report.report_id)
    forced_only_item = read_item(client, only_forced.report_id)
    unsucceeded_item = read_item(client, unsucceeded.report_id)
    listed = client.get(
        f"/v2/reports?country_id=us&report_id={report.report_id}"
        f"&report_id={unsucceeded.report_id}"
    ).json()["result"]["items"]

    assert (item["run"]["id"], item["status"]) == (str(succeeded), "succeeded")
    assert item["result"] is not None
    assert forced_only_item["run"] is None
    assert forced_only_item["status"] == "not_run"
    assert unsucceeded_item["run"]["id"] == str(newest_unforced)
    assert [summary["run"]["id"] for summary in listed] == [
        str(succeeded),
        str(newest_unforced),
    ]


def test_a_user_reads_their_own_newest_recorded_run(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    browsers: list[UUID],
) -> None:
    asker, other_user = browsers
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
        first_asked = store_run(
            connection, catalog, report, days_later=0, status="succeeded"
        )
        newest_asked = store_run(
            connection,
            catalog,
            report,
            days_later=1,
            status="running",
            versions=NEWER_VERSIONS,
        )
        newest_succeeded = store_run(
            connection,
            catalog,
            report,
            days_later=2,
            status="succeeded",
            versions={**CURRENT_VERSIONS, "policyengine_version": "4.4.0"},
        )
    simulation_service = JoiningSimulationService(owner_engine, catalog)
    client = client_for(runtime_sessions, simulation_service)
    for run_id in (first_asked, newest_asked):
        simulation_service.joined_run = JoinedRun(
            report_id=report.report_id, report_run_id=run_id
        )
        response = client.post(
            f"/v2/reports/{report.report_id}/runs?country_id=us",
            json={},
            headers=as_browser(asker),
        )
        assert response.status_code == 201, response.text

    askers_item = read_item(client, report.report_id, as_browser(asker))
    askers_listed = client.get(
        f"/v2/reports?country_id=us&report_id={report.report_id}",
        headers=as_browser(asker),
    ).json()["result"]["items"]
    others_item = read_item(client, report.report_id, as_browser(other_user))
    named_item = client.get(
        f"/v2/reports/{report.report_id}?country_id=us&run_id={first_asked}",
        headers=as_browser(asker),
    ).json()["result"]["item"]

    assert askers_item["run"]["id"] == str(newest_asked)
    assert askers_item["status"] == "running"
    assert [summary["run"]["id"] for summary in askers_listed] == [str(newest_asked)]
    assert others_item["run"]["id"] == str(newest_succeeded)
    assert named_item["run"]["id"] == str(first_asked)


def test_a_user_reads_the_window_run_of_their_newest_recorded_year(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    browsers: list[UUID],
) -> None:
    asker = browsers[0]
    with owner_engine.begin() as connection:
        asked = store_window(
            connection,
            catalog,
            years=(2026, 2027),
            settings=RunSettings(versions=CURRENT_VERSIONS, status="running"),
        )
        store_window(
            connection,
            catalog,
            years=(2026, 2027),
            settings=RunSettings(
                versions=NEWER_VERSIONS,
                status="pending",
                created_at=STARTED_AT + timedelta(days=1),
            ),
            report=asked.report,
        )
    simulation_service = JoiningSimulationService(
        owner_engine,
        catalog,
        joined_run=JoinedRun(
            report_id=asked.report.report_id,
            report_run_id=asked.year_run_ids[0],
            budget_window_run_id=asked.window_run_id,
        ),
    )
    client = client_for(runtime_sessions, simulation_service)
    response = client.post(
        f"/v2/reports/{asked.report.report_id}/runs?country_id=us",
        json={},
        headers=as_browser(asker),
    )
    assert response.status_code == 201, response.text

    item = read_item(client, asked.report.report_id, as_browser(asker))

    assert item["kind"] == "budget_window"
    assert item["run"]["id"] == str(asked.window_run_id)
    assert [year["year"] for year in item["run"]["years"]] == [2026, 2027]


def test_a_reports_label_and_description_are_the_users_saved_reports(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    browsers: list[UUID],
) -> None:
    saver, other_user = browsers
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
    store_saved_report(owner_engine, user_id=saver, report_id=report.report_id)
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE user_report_associations SET description = 'Mine' "
                "WHERE user_id = :user_id"
            ),
            {"user_id": saver},
        )
    client = client_for(
        runtime_sessions, JoiningSimulationService(owner_engine, catalog)
    )

    savers_item = read_item(client, report.report_id, as_browser(saver))
    savers_listed = client.get(
        f"/v2/reports?country_id=us&report_id={report.report_id}",
        headers=as_browser(saver),
    ).json()["result"]["items"]
    others_item = read_item(client, report.report_id, as_browser(other_user))
    anonymous_item = read_item(client, report.report_id)

    assert (savers_item["label"], savers_item["description"]) == ("My report", "Mine")
    assert [summary["label"] for summary in savers_listed] == ["My report"]
    assert (others_item["label"], others_item["description"]) == (None, None)
    assert (anonymous_item["label"], anonymous_item["description"]) == (None, None)


def test_a_malformed_browser_credential_on_a_read_is_refused(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
    client = client_for(
        runtime_sessions, JoiningSimulationService(owner_engine, catalog)
    )

    read = client.get(
        f"/v2/reports/{report.report_id}?country_id=us",
        headers={UNAUTHENTICATED_USER_HEADER: "not-a-uuid"},
    )
    listed = client.get(
        f"/v2/reports?country_id=us&report_id={report.report_id}",
        headers={UNAUTHENTICATED_USER_HEADER: "not-a-uuid"},
    )

    assert (read.status_code, listed.status_code) == (401, 401)


def test_the_newest_request_wins_whichever_run_was_created_last(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    browsers: list[UUID],
) -> None:
    asker = browsers[0]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
        # Not succeeded, so neither the default run nor the newest run.
        created_first = store_run(
            connection, catalog, report, days_later=0, status="pending"
        )
        created_last = store_run(
            connection,
            catalog,
            report,
            days_later=1,
            status="succeeded",
            versions=NEWER_VERSIONS,
        )
    simulation_service = JoiningSimulationService(owner_engine, catalog)
    client = client_for(runtime_sessions, simulation_service)
    # Asked for the run created last first, then the one created first.
    for run_id in (created_last, created_first):
        simulation_service.joined_run = JoinedRun(
            report_id=report.report_id, report_run_id=run_id
        )
        response = client.post(
            f"/v2/reports/{report.report_id}/runs?country_id=us",
            json={},
            headers=as_browser(asker),
        )
        assert response.status_code == 201, response.text

    item = read_item(client, report.report_id, as_browser(asker))

    assert item["run"]["id"] == str(created_first)


def test_a_recalculated_window_run_is_never_the_default(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    with owner_engine.begin() as connection:
        unrecalculated = store_window(
            connection,
            catalog,
            years=(2026, 2027),
            settings=RunSettings(versions=CURRENT_VERSIONS, status="pending"),
        )
        recalculated = store_window(
            connection,
            catalog,
            years=(2026, 2027),
            settings=RunSettings(
                versions=NEWER_VERSIONS,
                status="pending",
                created_at=STARTED_AT + timedelta(days=1),
            ),
            report=unrecalculated.report,
        )
        connection.execute(
            text("UPDATE budget_window_runs SET recalculate = true WHERE id = :id"),
            {"id": recalculated.window_run_id},
        )
    client = client_for(
        runtime_sessions, JoiningSimulationService(owner_engine, catalog)
    )

    item = read_item(client, unrecalculated.report.report_id)

    assert item["run"]["id"] == str(unrecalculated.window_run_id)


def test_of_two_saved_reports_of_one_report_the_one_saved_last_names_it(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    browsers: list[UUID],
) -> None:
    saver = browsers[0]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
    first_saved = store_saved_report(
        owner_engine, user_id=saver, report_id=report.report_id
    )
    last_saved = store_saved_report(
        owner_engine, user_id=saver, report_id=report.report_id
    )
    with owner_engine.begin() as connection:
        for saved_report_id, name, saved_at in (
            (first_saved, "First name", STARTED_AT),
            (last_saved, "Last name", STARTED_AT + timedelta(days=1)),
        ):
            connection.execute(
                text(
                    "UPDATE user_report_associations SET name = :name, "
                    "created_at = :saved_at WHERE id = :id"
                ),
                {"name": name, "saved_at": saved_at, "id": saved_report_id},
            )
    client = client_for(
        runtime_sessions, JoiningSimulationService(owner_engine, catalog)
    )

    item = read_item(client, report.report_id, as_browser(saver))

    assert item["label"] == "Last name"

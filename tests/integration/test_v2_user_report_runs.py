"""Create and re-run v2 reports whose runs other requests share, on PostgreSQL.

Once the simulation service finds or creates reports and runs by key, a
request may end on a run that already exists: it answers 201 naming that
run, and a re-run while a run is pending or running answers that run rather
than 409. A stand-in for the simulation service's client answers so: with a
run it names (``joined_run``), or else with a new pending run it stores. The
routes run as the Public API's runtime role and read the report back with
the run the answer names, whichever run is the report's newest.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
from policyengine_api.services.v2.identity.services import (
    convert_unauthenticated_user_in_session,
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.identity.types import (
    AccountConversionOutcome,
    UnauthenticatedPrincipal,
    UserPrincipal,
)
from policyengine_api.services.v2.user_reports.database_session import (
    UserReportDatabaseSession,
)
from policyengine_api.services.v2.user_reports.services import V2UserReportService
from policyengine_api.services.v2.user_reports.types import (
    UserReportCreateFields,
    UserReportUpdateInput,
)
from tests.integration.stored_report_rows import (
    STARTED_AT,
    BudgetWindowYear,
    RunSettings,
    delete_catalog,
    store_budget_window_run,
    store_catalog,
    store_report,
    store_report_run,
    store_year_simulations,
)
from tests.integration.user_report_run_support import (
    CURRENT_VERSIONS,
    WINDOW_YEARS,
    JoinedRun,
    JoiningSimulationService,
    UnwritableRecordSession,
    as_browser,
    client_for,
    newest_request,
    report_body,
    rerun_as_browser,
    saved_report_last_run_at,
    store_joined_and_newer_forced_run,
    store_saved_report,
    store_signed_in_user,
    stored_records,
)
from tests.unit.v2.user_service_support import default_legacy_references

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

    from tests.integration.stored_report_rows import CatalogRows


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


def test_a_create_that_joins_a_run_answers_that_run_not_the_reports_newest(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    with owner_engine.begin() as connection:
        report, joined_run_id, _forced_run_id = store_joined_and_newer_forced_run(
            connection, catalog, joined_status="succeeded"
        )
    simulation_service = JoiningSimulationService(
        owner_engine,
        catalog,
        joined_run=JoinedRun(report_id=report.report_id, report_run_id=joined_run_id),
    )

    response = client_for(runtime_sessions, simulation_service).post(
        "/v2/reports?country_id=us", json=report_body(catalog.policy_id)
    )

    assert response.status_code == 201, response.text
    item = response.json()["result"]["item"]
    assert item["id"] == str(report.report_id)
    assert item["run"]["id"] == str(joined_run_id)
    assert item["status"] == "succeeded"


def test_a_rerun_while_a_run_is_under_way_answers_201_with_that_run(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    with owner_engine.begin() as connection:
        report, joined_run_id, _forced_run_id = store_joined_and_newer_forced_run(
            connection, catalog, joined_status="pending"
        )
    simulation_service = JoiningSimulationService(
        owner_engine,
        catalog,
        joined_run=JoinedRun(report_id=report.report_id, report_run_id=joined_run_id),
    )

    response = client_for(runtime_sessions, simulation_service).post(
        f"/v2/reports/{report.report_id}/runs?country_id=us", json={}
    )

    assert response.status_code == 201, response.text
    item = response.json()["result"]["item"]
    assert item["run"]["id"] == str(joined_run_id)
    assert item["status"] == "pending"


def test_a_budget_window_rerun_answers_the_window_run_it_joined(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    with owner_engine.begin() as connection:
        window = store_report(connection, catalog, budget_window_size=2)
        window_run_ids = []
        first_year_run_ids = []
        for days_later in (0, 1):
            settings = RunSettings(
                versions=CURRENT_VERSIONS,
                status="pending",
                created_at=STARTED_AT + timedelta(days=days_later),
                forced=days_later == 1,
            )
            window_run_id = store_budget_window_run(
                connection, catalog, window, settings
            )
            window_run_ids.append(window_run_id)
            for year in WINDOW_YEARS:
                year_run = store_report_run(
                    connection,
                    catalog,
                    store_year_simulations(connection, catalog, window, year),
                    RunSettings(
                        versions=CURRENT_VERSIONS,
                        status="pending",
                        created_at=settings.created_at,
                        budget_window_year=BudgetWindowYear(
                            budget_window_run_id=window_run_id, year=year
                        ),
                        forced=settings.forced,
                    ),
                )
                if year == WINDOW_YEARS[0]:
                    first_year_run_ids.append(year_run.report_run_id)
    joined = JoinedRun(
        report_id=window.report_id,
        report_run_id=first_year_run_ids[0],
        budget_window_run_id=window_run_ids[0],
    )
    simulation_service = JoiningSimulationService(
        owner_engine, catalog, joined_run=joined
    )

    response = client_for(runtime_sessions, simulation_service).post(
        f"/v2/reports/{window.report_id}/runs?country_id=us", json={}
    )

    assert response.status_code == 201, response.text
    item = response.json()["result"]["item"]
    assert item["kind"] == "budget_window"
    assert item["run"]["id"] == str(window_run_ids[0])


@pytest.fixture
def browsers(owner_engine: Engine) -> Iterator[list[UUID]]:
    """Name signed-out browsers' users, and delete them and their records after."""
    browser_ids = [uuid4() for _ in range(2)]
    yield browser_ids
    with owner_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": browser_ids}
        )


def test_a_create_with_a_signed_out_browsers_credential_records_its_run(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    browsers: list[UUID],
) -> None:
    simulation_service = JoiningSimulationService(owner_engine, catalog)
    asked_at = datetime.now(UTC)

    response = client_for(runtime_sessions, simulation_service).post(
        "/v2/reports?country_id=us",
        json=report_body(catalog.policy_id),
        headers=as_browser(browsers[0]),
    )

    assert response.status_code == 201, response.text
    run_id = UUID(response.json()["result"]["item"]["run"]["id"])
    (record,) = stored_records(owner_engine, browsers)
    assert (record.user_id, record.report_run_id, record.trigger) == (
        browsers[0],
        run_id,
        "initial",
    )
    assert asked_at <= record.requested_at <= datetime.now(UTC)


def test_two_users_who_join_one_run_each_record_it(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    browsers: list[UUID],
) -> None:
    with owner_engine.begin() as connection:
        report, joined_run_id, _forced_run_id = store_joined_and_newer_forced_run(
            connection, catalog, joined_status="pending"
        )
    simulation_service = JoiningSimulationService(
        owner_engine,
        catalog,
        joined_run=JoinedRun(report_id=report.report_id, report_run_id=joined_run_id),
    )
    client = client_for(runtime_sessions, simulation_service)

    answers = [
        client.post(
            "/v2/reports?country_id=us",
            json=report_body(catalog.policy_id),
            headers=as_browser(browser_id),
        )
        for browser_id in browsers
    ]

    assert [answer.status_code for answer in answers] == [201, 201]
    records = stored_records(owner_engine, browsers)
    assert {(record.user_id, record.report_run_id) for record in records} == {
        (browsers[0], joined_run_id),
        (browsers[1], joined_run_id),
    }


def test_a_user_asking_again_for_a_run_they_have_keeps_their_first_record(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    browsers: list[UUID],
) -> None:
    with owner_engine.begin() as connection:
        report, joined_run_id, _forced_run_id = store_joined_and_newer_forced_run(
            connection, catalog, joined_status="pending"
        )
    simulation_service = JoiningSimulationService(
        owner_engine,
        catalog,
        joined_run=JoinedRun(report_id=report.report_id, report_run_id=joined_run_id),
    )
    client = client_for(runtime_sessions, simulation_service)
    first = client.post(
        "/v2/reports?country_id=us",
        json=report_body(catalog.policy_id),
        headers=as_browser(browsers[0]),
    )
    (first_record,) = stored_records(owner_engine, browsers)

    again = client.post(
        f"/v2/reports/{report.report_id}/runs?country_id=us",
        json={},
        headers=as_browser(browsers[0]),
    )

    assert (first.status_code, again.status_code) == (201, 201)
    assert stored_records(owner_engine, browsers) == [first_record]
    assert first_record.trigger == "initial"


def test_a_rerun_records_a_manual_request_for_the_run_it_ended_on(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    browsers: list[UUID],
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
    simulation_service = JoiningSimulationService(owner_engine, catalog)

    response = client_for(runtime_sessions, simulation_service).post(
        f"/v2/reports/{report.report_id}/runs?country_id=us",
        json={},
        headers=as_browser(browsers[0]),
    )

    assert response.status_code == 201, response.text
    run_id = UUID(response.json()["result"]["item"]["run"]["id"])
    (record,) = stored_records(owner_engine, browsers)
    assert (record.report_run_id, record.trigger) == (run_id, "manual")
    (rerun,) = simulation_service.reruns
    assert rerun.force is False


def test_a_request_without_a_user_credential_records_nothing(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    simulation_service = JoiningSimulationService(owner_engine, catalog)

    response = client_for(runtime_sessions, simulation_service).post(
        "/v2/reports?country_id=us", json=report_body(catalog.policy_id)
    )

    assert response.status_code == 201, response.text
    run_id = response.json()["result"]["item"]["run"]["id"]
    with owner_engine.begin() as connection:
        recorded = connection.execute(
            text(
                "SELECT count(*) FROM user_report_run_associations WHERE "
                "report_run_id = :id"
            ),
            {"id": run_id},
        ).scalar_one()
    assert recorded == 0


def test_a_browser_credential_naming_a_signed_in_user_is_refused_before_asking(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    browsers: list[UUID],
) -> None:
    signed_in_user_id = browsers[0]
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, user_type, primary_country) VALUES "
                "(:id, 'standard', 'us')"
            ),
            {"id": signed_in_user_id},
        )
    simulation_service = JoiningSimulationService(owner_engine, catalog)

    response = client_for(runtime_sessions, simulation_service).post(
        "/v2/reports?country_id=us",
        json=report_body(catalog.policy_id),
        headers=as_browser(signed_in_user_id),
    )

    assert response.status_code == 401, response.text
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert simulation_service.reports == []
    assert stored_records(owner_engine, browsers) == []


def test_a_malformed_browser_credential_is_refused_before_asking(
    owner_engine: Engine, catalog: CatalogRows, runtime_sessions: Any
) -> None:
    simulation_service = JoiningSimulationService(owner_engine, catalog)

    response = client_for(runtime_sessions, simulation_service).post(
        "/v2/reports?country_id=us",
        json=report_body(catalog.policy_id),
        headers={UNAUTHENTICATED_USER_HEADER: "not-a-uuid"},
    )

    assert response.status_code == 401, response.text
    assert simulation_service.reports == []


def test_a_saved_reports_last_run_at_is_its_owners_newest_request(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    browsers: list[UUID],
) -> None:
    # An admin, who may force a re-run, so each re-run is a new run.
    owner, owner_id = store_signed_in_user(
        runtime_sessions, owner_engine, user_type="admin"
    )
    browsers.append(owner_id)
    other_user_id = browsers[0]
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
    saved_report_id = store_saved_report(
        owner_engine, user_id=owner_id, report_id=report.report_id
    )
    others_saved_report_id = store_saved_report(
        owner_engine, user_id=other_user_id, report_id=report.report_id
    )
    client = client_for(
        runtime_sessions,
        JoiningSimulationService(owner_engine, catalog),
        requester=owner,
    )

    for _ in range(2):
        response = client.post(
            f"/v2/reports/{report.report_id}/runs?country_id=us",
            json={"force": True},
        )
        assert response.status_code == 201, response.text

    newest_request = max(
        record.requested_at for record in stored_records(owner_engine, [owner_id])
    )
    assert saved_report_last_run_at(owner_engine, saved_report_id) == newest_request
    assert saved_report_last_run_at(owner_engine, others_saved_report_id) is None


def test_a_run_whose_record_cannot_be_written_answers_503_naming_it(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    browsers: list[UUID],
) -> None:
    simulation_service = JoiningSimulationService(owner_engine, catalog)

    response = client_for(
        runtime_sessions,
        simulation_service,
        record_session=UnwritableRecordSession(runtime_sessions),
    ).post(
        "/v2/reports?country_id=us",
        json=report_body(catalog.policy_id),
        headers=as_browser(browsers[0]),
    )

    assert response.status_code == 503, response.text
    body = response.json()
    report_id = catalog.report_ids[-1]
    with owner_engine.begin() as connection:
        run_id = connection.execute(
            text("SELECT id FROM report_runs WHERE report_id = :id"),
            {"id": report_id},
        ).scalar_one()
    assert body["report_id"] == str(report_id)
    assert body["run_id"] == str(run_id)
    assert f"run_id={run_id}" in body["message"]
    assert stored_records(owner_engine, browsers) == []


def test_a_sign_in_merge_moves_the_browsers_run_records_into_the_account(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    browsers: list[UUID],
) -> None:
    browser_id = browsers[0]
    with owner_engine.begin() as connection:
        alone_report, alone_run_id, _ = store_joined_and_newer_forced_run(
            connection, catalog, joined_status="pending"
        )
        shared_report, shared_run_id, _ = store_joined_and_newer_forced_run(
            connection, catalog, joined_status="pending"
        )
        accounts_own_report, accounts_own_run_id, _ = store_joined_and_newer_forced_run(
            connection, catalog, joined_status="pending"
        )
    account = UserPrincipal(issuer="https://users.example.test/", subject="auth0|merge")
    with runtime_sessions.begin() as session:
        account_id = resolve_principal_user_in_session(
            session, account, country_id="us"
        ).user_id
    browsers.append(account_id)
    account_asked_at = datetime(2026, 1, 1, tzinfo=UTC)
    # Later than any request the browser makes in this test.
    account_asked_for_its_own_at = datetime(2030, 1, 1, tzinfo=UTC)
    with owner_engine.begin() as connection:
        for run_id, requested_at in (
            (shared_run_id, account_asked_at),
            (accounts_own_run_id, account_asked_for_its_own_at),
        ):
            connection.execute(
                text(
                    "INSERT INTO user_report_run_associations (id, user_id, "
                    "report_run_id, requested_at, trigger) VALUES (:id, "
                    ":user_id, :run_id, :requested_at, 'initial')"
                ),
                {
                    "id": uuid4(),
                    "user_id": account_id,
                    "run_id": run_id,
                    "requested_at": requested_at,
                },
            )
    account_saved_report_id = store_saved_report(
        owner_engine, user_id=account_id, report_id=alone_report.report_id
    )
    browser_saved_report_id = store_saved_report(
        owner_engine, user_id=browser_id, report_id=shared_report.report_id
    )
    # The browser saved a report it never asked to run, but the account did.
    browsers_unrun_saved_report_id = store_saved_report(
        owner_engine, user_id=browser_id, report_id=accounts_own_report.report_id
    )
    simulation_service = JoiningSimulationService(owner_engine, catalog)
    client = client_for(runtime_sessions, simulation_service)
    for report, run_id in (
        (alone_report, alone_run_id),
        (shared_report, shared_run_id),
    ):
        simulation_service.joined_run = JoinedRun(
            report_id=report.report_id, report_run_id=run_id
        )
        response = client.post(
            "/v2/reports?country_id=us",
            json=report_body(catalog.policy_id),
            headers=as_browser(browser_id),
        )
        assert response.status_code == 201, response.text
    browser_asked_at = {
        record.report_run_id: record.requested_at
        for record in stored_records(owner_engine, [browser_id])
    }

    with runtime_sessions.begin() as session:
        conversion = convert_unauthenticated_user_in_session(
            session,
            unauthenticated_user_id=browser_id,
            principal=account,
            country_id="us",
        )

    assert conversion.outcome is AccountConversionOutcome.MERGED
    records = stored_records(owner_engine, [account_id, browser_id])
    # A run the account had already asked for keeps the account's record.
    assert {
        (record.user_id, record.report_run_id, record.requested_at)
        for record in records
    } == {
        (account_id, alone_run_id, browser_asked_at[alone_run_id]),
        (account_id, shared_run_id, account_asked_at),
        (account_id, accounts_own_run_id, account_asked_for_its_own_at),
    }
    assert {record.trigger for record in records} == {"initial"}
    # Every saved report the account now holds shows the account's newest
    # request for its report: its own saved report takes the request that
    # moved in, and the browser's moved saved reports take the account's
    # records, whatever time they held before.
    assert (
        saved_report_last_run_at(owner_engine, account_saved_report_id)
        == browser_asked_at[alone_run_id]
    )
    assert (
        saved_report_last_run_at(owner_engine, browser_saved_report_id)
        == account_asked_at
    )
    assert (
        saved_report_last_run_at(owner_engine, browsers_unrun_saved_report_id)
        == account_asked_for_its_own_at
    )


def test_saving_or_repointing_a_report_takes_its_owners_newest_request(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    browsers: list[UUID],
) -> None:
    owner_id = browsers[0]
    owner = UnauthenticatedPrincipal(user_id=owner_id)
    with owner_engine.begin() as connection:
        first_report = store_report(connection, catalog)
        second_report = store_report(connection, catalog)
        never_run_report = store_report(connection, catalog)
    client = client_for(
        runtime_sessions, JoiningSimulationService(owner_engine, catalog)
    )
    saved_reports = V2UserReportService(
        UserReportDatabaseSession(runtime_sessions), default_legacy_references()
    )
    callers_time = datetime(2020, 1, 1, tzinfo=UTC)
    rerun_as_browser(client, first_report.report_id, owner_id)
    first_request = newest_request(owner_engine, owner_id)

    saved = saved_reports.create_user_report(
        principal=owner,
        association_input=UserReportCreateFields(
            country_id="us",
            report_id=first_report.report_id,
            last_run_at=callers_time,
        ),
    )
    never_run = saved_reports.create_user_report(
        principal=owner,
        association_input=UserReportCreateFields(
            country_id="us",
            report_id=never_run_report.report_id,
            last_run_at=callers_time,
        ),
    )
    rerun_as_browser(client, second_report.report_id, owner_id)
    second_request = newest_request(owner_engine, owner_id)
    repointed = saved_reports.patch_user_report(
        principal=owner,
        country_id="us",
        association_id=saved.id,
        association_input=UserReportUpdateInput(report_id=second_report.report_id),
    )
    given_a_time = saved_reports.patch_user_report(
        principal=owner,
        country_id="us",
        association_id=saved.id,
        association_input=UserReportUpdateInput(last_run_at=callers_time),
    )
    renamed = saved_reports.patch_user_report(
        principal=owner,
        country_id="us",
        association_id=saved.id,
        association_input=UserReportUpdateInput(name="Renamed"),
    )

    assert saved.last_run_at == first_request
    assert never_run.last_run_at is None
    assert repointed.last_run_at == second_request
    assert given_a_time.last_run_at == second_request
    assert renamed.last_run_at == second_request


@pytest.mark.parametrize("request_kind", ["create", "rerun"])
def test_a_run_that_cannot_be_read_back_is_named_in_the_502(
    owner_engine: Engine,
    catalog: CatalogRows,
    runtime_sessions: Any,
    request_kind: str,
) -> None:
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
    # The answer names a run the report doesn't have, so reading it back fails.
    unreadable_run_id = uuid4()
    simulation_service = JoiningSimulationService(
        owner_engine,
        catalog,
        joined_run=JoinedRun(
            report_id=report.report_id, report_run_id=unreadable_run_id
        ),
    )
    client = client_for(runtime_sessions, simulation_service)

    response = (
        client.post("/v2/reports?country_id=us", json=report_body(catalog.policy_id))
        if request_kind == "create"
        else client.post(f"/v2/reports/{report.report_id}/runs?country_id=us", json={})
    )

    assert response.status_code == 502, response.text
    body = response.json()
    assert body["report_id"] == str(report.report_id)
    assert body["run_id"] == str(unreadable_run_id)
    assert f"run_id={unreadable_run_id}" in body["message"]

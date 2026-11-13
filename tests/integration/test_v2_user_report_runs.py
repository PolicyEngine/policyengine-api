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

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from flask import Flask
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel import Session

from policyengine_api.asgi_factory import create_asgi_app
from policyengine_api.constants import REPO
from policyengine_api.fastapi_routes.dependencies import NativeRouteDependencies
from policyengine_api.libs.user_auth import UNAUTHENTICATED_USER_HEADER
from policyengine_api.migration_flags import (
    RouteImplementation,
    RouteImplementationSettings,
)
from policyengine_api.services.v2.countries.database_session import (
    CountryDatabaseSession,
)
from policyengine_api.services.v2.countries.services import V2CountryService
from policyengine_api.services.v2.households.database_session import (
    HouseholdDatabaseSession,
)
from policyengine_api.services.v2.households.services import V2HouseholdService
from policyengine_api.services.v2.identity.services import (
    convert_unauthenticated_user_in_session,
    resolve_principal_user_in_session,
)
from policyengine_api.services.v2.identity.types import (
    AccountConversionOutcome,
    UserPrincipal,
)
from policyengine_api.services.v2.policies.database_session import (
    PolicyDatabaseSession,
)
from policyengine_api.services.v2.policies.services import V2PolicyService
from policyengine_api.services.v2.report_run_records.database_session import (
    ReportRunRecordDatabaseSession,
)
from policyengine_api.services.v2.report_run_records.services import (
    ReportRunRecordService,
)
from policyengine_api.services.v2.simulation_service.services import (
    SimulationSubmissionService,
)
from policyengine_api.services.v2.simulation_service.types import (
    PackageVersions,
    ReportRerunInput,
    StartedReportRun,
    SubmittedReport,
)
from policyengine_api.services.v2.stored_reports.database_session import (
    StoredReportDatabaseSession,
)
from policyengine_api.services.v2.stored_reports.services import V2StoredReportService
from tests.fixtures.economy_results import us_economy_result
from tests.integration.stored_report_rows import (
    STARTED_AT,
    BudgetWindowYear,
    RunSettings,
    StoredReport,
    delete_catalog,
    store_budget_window_run,
    store_catalog,
    store_report,
    store_report_run,
    store_year_simulations,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from contextlib import AbstractContextManager

    from sqlalchemy import Engine

    from policyengine_api.services.v2.simulation_service.types import (
        EconomyReportCreationInput,
    )
    from tests.integration.stored_report_rows import CatalogRows

CURRENT_VERSIONS = {"country_package_version": "1.5.0", "policyengine_version": "4.2.0"}
WINDOW_YEARS = (2026, 2027)


def current_versions(country_id: str) -> PackageVersions:
    return PackageVersions(**CURRENT_VERSIONS)


@dataclass(frozen=True)
class JoinedRun:
    """A run an answer names that the request didn't create.

    ``budget_window_run_id`` is set for a budget window's run, whose first
    year's report run is ``report_run_id``.
    """

    report_id: UUID
    report_run_id: UUID
    budget_window_run_id: UUID | None = None


@dataclass
class JoiningSimulationService:
    """Answer as the simulation service does once identical requests share runs.

    With ``joined_run``, every create and re-run answers that run and stores
    nothing, as a request that finds an existing run does. Without it, a
    create stores a new report with a pending run, and a re-run a new pending
    run of the report, as before, marked forced for a forced re-run.
    """

    engine: Engine
    catalog: CatalogRows
    joined_run: JoinedRun | None = None
    reports: list[EconomyReportCreationInput] = field(default_factory=list)
    reruns: list[ReportRerunInput] = field(default_factory=list)

    def submit_report(self, report: EconomyReportCreationInput) -> SubmittedReport:
        self.reports.append(report)
        if self.joined_run is not None:
            return SubmittedReport(
                report_id=self.joined_run.report_id,
                report_run_id=self.joined_run.report_run_id,
            )
        with self.engine.begin() as connection:
            stored = store_report(connection, self.catalog)
            run_ids = store_report_run(
                connection,
                self.catalog,
                stored,
                RunSettings(versions=CURRENT_VERSIONS, status="pending"),
            )
        return SubmittedReport(
            report_id=stored.report_id, report_run_id=run_ids.report_run_id
        )

    def rerun_report(self, rerun: ReportRerunInput) -> StartedReportRun:
        self.reruns.append(rerun)
        if self.joined_run is not None:
            return StartedReportRun(
                report_run_id=self.joined_run.report_run_id,
                budget_window_run_id=self.joined_run.budget_window_run_id,
            )
        with self.engine.begin() as connection:
            simulations = connection.execute(
                text(
                    "SELECT baseline_simulation_id, reform_simulation_id FROM "
                    "reports WHERE id = :id"
                ),
                {"id": rerun.report_id},
            ).one()
            run_ids = store_report_run(
                connection,
                self.catalog,
                StoredReport(
                    report_id=rerun.report_id,
                    baseline_simulation_id=simulations.baseline_simulation_id,
                    reform_simulation_id=simulations.reform_simulation_id,
                ),
                RunSettings(
                    versions=CURRENT_VERSIONS,
                    status="pending",
                    created_at=STARTED_AT + timedelta(days=30),
                    forced=rerun.force,
                ),
            )
        return StartedReportRun(report_run_id=run_ids.report_run_id)


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


class UnwritableRecordSession(ReportRunRecordDatabaseSession):
    """Read as usual, but fail every transaction, as an unavailable database does."""

    def transaction(self) -> AbstractContextManager[Session]:
        statement = "INSERT INTO user_report_run_associations"
        raise OperationalError(statement, {}, Exception("connection refused"))


def client_for(
    sessions: Any,
    simulation_service: JoiningSimulationService,
    *,
    record_session: ReportRunRecordDatabaseSession | None = None,
) -> TestClient:
    """Serve the report routes as the runtime role, through the stand-in.

    Users' report runs are recorded through ``record_session``, by default
    the runtime role's.
    """
    submissions = SimulationSubmissionService(
        countries=V2CountryService(CountryDatabaseSession(sessions)),
        households=V2HouseholdService(HouseholdDatabaseSession(sessions)),
        policies=V2PolicyService(
            PolicyDatabaseSession(sessions), running_policyengine_version="4.2.0"
        ),
        client_factory=lambda: simulation_service,
    )
    dependencies = NativeRouteDependencies(
        readiness_probe=lambda: True,
        gateway_client_factory=lambda: None,
        metadata_reader_factory=lambda: None,
        v2_stored_report_service_factory=lambda: V2StoredReportService(
            StoredReportDatabaseSession(sessions),
            current_versions=current_versions,
            submissions=submissions,
            run_records=ReportRunRecordService(
                record_session or ReportRunRecordDatabaseSession(sessions)
            ),
        ),
    )
    settings = RouteImplementationSettings(
        health=RouteImplementation.FLASK_FALLBACK,
        specification=RouteImplementation.FLASK_FALLBACK,
        metadata=RouteImplementation.FLASK_FALLBACK,
    )
    return TestClient(
        create_asgi_app(
            Flask(__name__), dependencies=dependencies, route_settings=settings
        )
    )


def report_body(policy_id: UUID) -> dict[str, Any]:
    return {
        "country_id": "us",
        "kind": "economy",
        "label": "Expanded child tax credit",
        "year": 2026,
        "region_code": "state/ca",
        "baseline": {},
        "reform": {"policy_id": str(policy_id)},
    }


def store_joined_and_newer_forced_run(
    connection: Any, catalog: CatalogRows, *, joined_status: str
) -> tuple[StoredReport, UUID, UUID]:
    """Store a report with a run to join and a newer forced run beside it.

    A succeeded run to join has its result stored. Return the report, the
    run to join and the forced run, which is the report's newest.
    """
    report = store_report(connection, catalog)
    joined = store_report_run(
        connection,
        catalog,
        report,
        RunSettings(versions=CURRENT_VERSIONS, status=joined_status),
        result=us_economy_result() if joined_status == "succeeded" else None,
    )
    forced = store_report_run(
        connection,
        catalog,
        report,
        RunSettings(
            versions=CURRENT_VERSIONS,
            status="running",
            created_at=STARTED_AT + timedelta(days=1),
            forced=True,
        ),
    )
    return report, joined.report_run_id, forced.report_run_id


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


@dataclass(frozen=True)
class RunRecord:
    """A user's stored request for a report run."""

    user_id: UUID
    report_run_id: UUID
    trigger: str
    requested_at: datetime


@pytest.fixture
def browsers(owner_engine: Engine) -> Iterator[list[UUID]]:
    """Name signed-out browsers' users, and delete them and their records after."""
    browser_ids = [uuid4() for _ in range(2)]
    yield browser_ids
    with owner_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": browser_ids}
        )


def as_browser(browser_id: UUID) -> dict[str, str]:
    return {UNAUTHENTICATED_USER_HEADER: str(browser_id)}


def stored_records(engine: Engine, user_ids: list[UUID]) -> list[RunRecord]:
    with engine.begin() as connection:
        rows = connection.execute(
            text(
                "SELECT user_id, report_run_id, trigger, requested_at FROM "
                "user_report_run_associations WHERE user_id = ANY(:ids) "
                "ORDER BY requested_at, user_id"
            ),
            {"ids": user_ids},
        ).all()
    return [
        RunRecord(
            user_id=row.user_id,
            report_run_id=row.report_run_id,
            trigger=row.trigger,
            requested_at=row.requested_at,
        )
        for row in rows
    ]


def store_saved_report(engine: Engine, *, user_id: UUID, report_id: UUID) -> UUID:
    """Save the report for the user, with no last run time, and return its ID."""
    saved_report_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, user_type) VALUES (:id, 'unauthenticated') "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": user_id},
        )
        connection.execute(
            text(
                "INSERT INTO user_report_associations (id, user_id, report_id, "
                "country_id, name) VALUES (:id, :user_id, :report_id, 'us', "
                "'My report')"
            ),
            {"id": saved_report_id, "user_id": user_id, "report_id": report_id},
        )
    return saved_report_id


def saved_report_last_run_at(engine: Engine, saved_report_id: UUID) -> datetime | None:
    with engine.begin() as connection:
        return connection.execute(
            text("SELECT last_run_at FROM user_report_associations WHERE id = :id"),
            {"id": saved_report_id},
        ).scalar_one()


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
        json={"force": True},
        headers=as_browser(browsers[0]),
    )

    assert response.status_code == 201, response.text
    run_id = UUID(response.json()["result"]["item"]["run"]["id"])
    (record,) = stored_records(owner_engine, browsers)
    assert (record.report_run_id, record.trigger) == (run_id, "manual")
    (rerun,) = simulation_service.reruns
    assert rerun.force is True


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
    owner_id, other_user_id = browsers
    with owner_engine.begin() as connection:
        report = store_report(connection, catalog)
    saved_report_id = store_saved_report(
        owner_engine, user_id=owner_id, report_id=report.report_id
    )
    others_saved_report_id = store_saved_report(
        owner_engine, user_id=other_user_id, report_id=report.report_id
    )
    client = client_for(
        runtime_sessions, JoiningSimulationService(owner_engine, catalog)
    )

    # Forced, so each re-run is a new run beside the others.
    for _ in range(2):
        response = client.post(
            f"/v2/reports/{report.report_id}/runs?country_id=us",
            json={"force": True},
            headers=as_browser(owner_id),
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
    assert body["report_run_id"] == str(run_id)
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
    account = UserPrincipal(issuer="https://users.example.test/", subject="auth0|merge")
    with runtime_sessions.begin() as session:
        account_id = resolve_principal_user_in_session(
            session, account, country_id="us"
        ).user_id
    browsers.append(account_id)
    account_asked_at = datetime(2026, 1, 1, tzinfo=UTC)
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO user_report_run_associations (id, user_id, "
                "report_run_id, requested_at, trigger) VALUES (:id, :user_id, "
                ":run_id, :requested_at, 'initial')"
            ),
            {
                "id": uuid4(),
                "user_id": account_id,
                "run_id": shared_run_id,
                "requested_at": account_asked_at,
            },
        )
    account_saved_report_id = store_saved_report(
        owner_engine, user_id=account_id, report_id=alone_report.report_id
    )
    browser_saved_report_id = store_saved_report(
        owner_engine, user_id=browser_id, report_id=shared_report.report_id
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
    }
    assert {record.trigger for record in records} == {"initial"}
    # The account's saved report takes the time of the request that moved in;
    # the browser's moved saved report keeps its own.
    assert (
        saved_report_last_run_at(owner_engine, account_saved_report_id)
        == browser_asked_at[alone_run_id]
    )
    assert (
        saved_report_last_run_at(owner_engine, browser_saved_report_id)
        == browser_asked_at[shared_run_id]
    )

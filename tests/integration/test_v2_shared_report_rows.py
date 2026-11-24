"""Identical requests end on the same simulations, reports and runs.

The simulation service finds each simulation and report by its key, and joins
a run on the same versions that hasn't failed, with ``INSERT ... ON CONFLICT
DO NOTHING`` against the indexes the shared-report revision adds; a forced
re-run is an extra run that nothing joins. API v1 records each user's
request for a report run. Each statement runs as the role that runs it in
staging and production, holding only its declared privileges
(``policyengine_api/data/v2/privileges.py``).

Every statement runs through one Session of the database's owner, which
``act_as`` switches to a role for the rest of its transaction and
``act_as_owner`` returns to the owner. The partial indexes' conditions are
sent as literals, as the indexes hold them, so PostgreSQL matches the index
however often a statement runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import (
    and_,
    delete,
    func,
    insert,
    not_,
    select,
    true,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlmodel import col

from policyengine_api.constants import REPO
from policyengine_api.data.v2.models import (
    BudgetWindowRun,
    Report,
    ReportRun,
    ReportRunStatus,
    Simulation,
    SimulationRun,
    SimulationStatus,
    User,
    UserReportRunAssociation,
)
from tests.fixtures.database_sessions import act_as, act_as_owner, query_plan
from tests.integration.privilege_statements import (
    ReportColumns,
    SimulationColumns,
    unfailed,
    update_row,
)
from tests.integration.simulation_rows import (
    RUN_VERSIONS,
    PublicApiRows,
    add_row,
    insert_public_api_rows,
    refused,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Executable
    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

    from tests.integration.conftest import ManagedV2Roles

# SHA-256 digests, as the simulation service computes keys.
NATIONAL_KEY = "4bb1299756cb0a89" * 4
LOCAL_AREA_KEY = "907455a2702b0559" * 4
DATASET_INDEPENDENT_KEY = "bcabc98b4e0d3eff" * 4
NEWER_VERSIONS = {"country_package_version": "1.1.0", "policyengine_version": "4.1.0"}
# The keyed tables' mapped classes, by the table names the key tests use.
KEYED_MODELS: dict[str, type[Any]] = {
    "simulations": Simulation,
    "reports": Report,
}


# What the simulation service will send: a new row, or nothing when one with
# the same key, or an unfailed unforced run on the same versions, exists.
def _find_or_create_simulation(public_api_rows: PublicApiRows, key: str) -> Executable:
    return (
        postgresql.insert(Simulation)
        .values(
            id=uuid4(),
            simulation_type="economy",
            dataset_id=public_api_rows.dataset_id,
            tax_benefit_model_version_id=public_api_rows.version_id,
            year=2026,
            key_version=1,
            definition_key=key,
        )
        .on_conflict_do_nothing(
            index_elements=[col(Simulation.key_version), col(Simulation.definition_key)]
        )
        .returning(col(Simulation.id))
    )


def _find_or_create_report(public_api_rows: PublicApiRows, key: str) -> Executable:
    return (
        postgresql.insert(Report)
        .values(
            id=uuid4(),
            country="us",
            tax_benefit_model_id=public_api_rows.model_id,
            year=2026,
            inputs={},
            key_version=1,
            definition_key=key,
            dataset_independent_key=DATASET_INDEPENDENT_KEY,
        )
        .on_conflict_do_nothing(
            index_elements=[col(Report.key_version), col(Report.definition_key)]
        )
        .returning(col(Report.id))
    )


def _find_or_create_simulation_run(
    public_api_rows: PublicApiRows,
    simulation_id: UUID,
    *,
    year: int,
    versions: dict[str, str],
    forced: bool,
) -> Executable:
    return (
        postgresql.insert(SimulationRun)
        .values(
            id=uuid4(),
            simulation_id=simulation_id,
            year=year,
            tax_benefit_model_version_id=public_api_rows.version_id,
            status="pending",
            forced=forced,
            **versions,
        )
        .on_conflict_do_nothing(
            index_elements=[
                col(SimulationRun.simulation_id),
                col(SimulationRun.year),
                col(SimulationRun.tax_benefit_model_version_id),
                col(SimulationRun.country_package_version),
                col(SimulationRun.policyengine_version),
            ],
            index_where=and_(
                unfailed(col(SimulationRun.status), SimulationStatus.FAILED),
                not_(col(SimulationRun.forced)),
            ),
        )
        .returning(col(SimulationRun.id))
    )


def _find_or_create_report_run(
    report_id: UUID,
    baseline_run_id: UUID | None,
    *,
    versions: dict[str, str],
    forced: bool,
) -> Executable:
    return (
        postgresql.insert(ReportRun)
        .values(
            id=uuid4(),
            report_id=report_id,
            baseline_simulation_run_id=baseline_run_id,
            status="pending",
            forced=forced,
            **versions,
        )
        .on_conflict_do_nothing(
            index_elements=[
                col(ReportRun.report_id),
                col(ReportRun.country_package_version),
                col(ReportRun.policyengine_version),
            ],
            index_where=and_(
                col(ReportRun.budget_window_run_id).is_(None),
                unfailed(col(ReportRun.status), ReportRunStatus.FAILED),
                not_(col(ReportRun.forced)),
            ),
        )
        .returning(col(ReportRun.id))
    )


def _find_or_create_window_run(
    public_api_rows: PublicApiRows,
    report_id: UUID,
    *,
    policyengine_version: str,
    recalculate: bool,
) -> Executable:
    return (
        postgresql.insert(BudgetWindowRun)
        .values(
            id=uuid4(),
            report_id=report_id,
            tax_benefit_model_version_id=public_api_rows.version_id,
            policyengine_version=policyengine_version,
            recalculate=recalculate,
            status="pending",
        )
        .on_conflict_do_nothing(
            index_elements=[
                col(BudgetWindowRun.report_id),
                col(BudgetWindowRun.tax_benefit_model_version_id),
                col(BudgetWindowRun.policyengine_version),
            ],
            index_where=and_(
                unfailed(col(BudgetWindowRun.status), ReportRunStatus.FAILED),
                not_(col(BudgetWindowRun.recalculate)),
            ),
        )
        .returning(col(BudgetWindowRun.id))
    )


def _record_request(
    user_id: UUID,
    report_run_id: UUID | None,
    trigger: str,
    record_id: UUID | None = None,
) -> Executable:
    """Build API v1's record of the user's request for the report run."""
    return insert(UserReportRunAssociation).values(
        id=uuid4() if record_id is None else record_id,
        user_id=user_id,
        report_run_id=report_run_id,
        requested_at=func.now(),
        trigger=trigger,
    )


@pytest.fixture
def session(
    v2_owner_sessions: sessionmaker[Session], managed_v2_roles: ManagedV2Roles
) -> Iterator[Session]:
    """Yield a Session at head whose writes are rolled back after the test.

    It acts as the disposable database's owner (superuser), which owns every
    table; ``act_as`` switches it to one managed role and ``act_as_owner``
    back.
    """
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    with v2_owner_sessions() as owner_session:
        try:
            yield owner_session
        finally:
            owner_session.rollback()


@pytest.fixture
def public_api_rows(session: Session) -> PublicApiRows:
    return insert_public_api_rows(session)


def _inserted_id(session: Session, statement: Executable) -> UUID | None:
    """Run an ``INSERT ... RETURNING id``; return the new row's ID, or None."""
    inserted: UUID | None = session.execute(statement).scalar_one_or_none()
    return inserted


def _refused(
    session: Session,
    statement: Executable,
    error: type[Exception] = IntegrityError,
    match: str | None = None,
) -> None:
    with refused(session, error, match=match):
        session.execute(statement)


def _simulation(
    session: Session, public_api_rows: PublicApiRows, key: str | None = None
) -> UUID:
    """Create an economy simulation of 2026, keyed when ``key`` is given."""
    simulation_id = uuid4()
    add_row(
        session,
        Simulation,
        id=simulation_id,
        simulation_type="economy",
        dataset_id=public_api_rows.dataset_id,
        tax_benefit_model_version_id=public_api_rows.version_id,
        year=2026,
        key_version=None if key is None else 1,
        definition_key=key,
    )
    return simulation_id


def _simulation_run(  # noqa: PLR0913  # the simulation, then each part of its run
    session: Session,
    public_api_rows: PublicApiRows,
    simulation_id: UUID,
    *,
    year: int = 2026,
    versions: dict[str, str] = RUN_VERSIONS,
    forced: bool = False,
) -> UUID | None:
    """Find or create the simulation's run; return its ID if this call created it."""
    return _inserted_id(
        session,
        _find_or_create_simulation_run(
            public_api_rows, simulation_id, year=year, versions=versions, forced=forced
        ),
    )


def _report(session: Session, public_api_rows: PublicApiRows) -> UUID:
    report_id = uuid4()
    add_row(
        session,
        Report,
        id=report_id,
        country="us",
        tax_benefit_model_id=public_api_rows.model_id,
        year=2026,
        inputs={},
    )
    return report_id


def _report_run(
    session: Session,
    report_id: UUID,
    baseline_run_id: UUID | None,
    *,
    versions: dict[str, str] = RUN_VERSIONS,
    forced: bool = False,
) -> UUID | None:
    """Find or create the report's run; return its ID if this call created it."""
    return _inserted_id(
        session,
        _find_or_create_report_run(
            report_id, baseline_run_id, versions=versions, forced=forced
        ),
    )


def _fail(session: Session, model: type[Any], run_id: UUID | None) -> None:
    session.execute(
        update_row(
            model,
            run_id,
            status="failed",
            error_message="failed",
            completed_at=func.now(),
            updated_at=func.now(),
        )
    )


def _user(session: Session) -> UUID:
    user_id = uuid4()
    add_row(session, User, id=user_id, user_type="standard", primary_country="us")
    return user_id


def test_identical_keys_name_one_simulation_and_one_report(
    session: Session, managed_v2_roles: ManagedV2Roles, public_api_rows: PublicApiRows
) -> None:
    act_as(session, managed_v2_roles.simulation_service)

    simulation_id = _inserted_id(
        session, _find_or_create_simulation(public_api_rows, NATIONAL_KEY)
    )
    joined_simulation = _inserted_id(
        session, _find_or_create_simulation(public_api_rows, NATIONAL_KEY)
    )
    national_report = _inserted_id(
        session, _find_or_create_report(public_api_rows, NATIONAL_KEY)
    )
    joined_report = _inserted_id(
        session, _find_or_create_report(public_api_rows, NATIONAL_KEY)
    )
    # The local-area report is its own report, linked by the shared key.
    local_area_report = _inserted_id(
        session, _find_or_create_report(public_api_rows, LOCAL_AREA_KEY)
    )

    assert simulation_id is not None
    assert joined_simulation is None
    assert national_report is not None
    assert joined_report is None
    assert local_area_report not in {None, national_report}
    found = session.execute(
        select(col(Simulation.id)).where(
            col(Simulation.key_version) == 1,
            col(Simulation.definition_key) == NATIONAL_KEY,
        )
    ).scalar_one()
    assert found == simulation_id
    linked = session.execute(
        select(func.count())
        .select_from(Report)
        .where(col(Report.dataset_independent_key) == DATASET_INDEPENDENT_KEY)
    ).scalar_one()
    assert linked == 2
    # Rows from before the keys, and a later key format, stay apart.
    assert _simulation(session, public_api_rows) != _simulation(
        session, public_api_rows
    )
    add_row(
        session,
        Simulation,
        id=uuid4(),
        simulation_type="economy",
        dataset_id=public_api_rows.dataset_id,
        tax_benefit_model_version_id=public_api_rows.version_id,
        year=2026,
        key_version=2,
        definition_key=NATIONAL_KEY,
    )


def test_the_public_api_finds_reports_by_the_shared_key_alone(
    session: Session, managed_v2_roles: ManagedV2Roles, public_api_rows: PublicApiRows
) -> None:
    """The app looks a local-area report up by the national report's key.

    The key holds its own key version, so the lookup names the key alone, and
    the index on that column alone serves it.
    """
    act_as(session, managed_v2_roles.simulation_service)
    stored_report_ids = {
        _inserted_id(session, _find_or_create_report(public_api_rows, key))
        for key in (NATIONAL_KEY, LOCAL_AREA_KEY)
    }
    act_as(session, managed_v2_roles.runtime)
    lookup = select(col(Report.id)).where(
        col(Report.dataset_independent_key) == DATASET_INDEPENDENT_KEY
    )

    found_report_ids = set(session.execute(lookup).scalars())
    # SET LOCAL enable_seqscan = off: set_config's true keeps it to the
    # transaction.
    session.execute(select(func.set_config("enable_seqscan", "off", true())))
    plan = query_plan(session, lookup)

    assert found_report_ids == stored_report_ids
    assert None not in stored_report_ids
    assert "using ix_reports_dataset_independent_key on reports" in plan


@pytest.mark.parametrize(
    ("table", "key_columns"),
    [
        ("simulations", {"key_version": 1, "definition_key": NATIONAL_KEY.upper()}),
        ("simulations", {"key_version": 1, "definition_key": NATIONAL_KEY[:63]}),
        # Lowercase, 64 characters, but not hexadecimal.
        ("simulations", {"key_version": 1, "definition_key": "g" * 64}),
        ("simulations", {"key_version": 0, "definition_key": NATIONAL_KEY}),
        ("simulations", {"key_version": None, "definition_key": NATIONAL_KEY}),
        ("simulations", {"key_version": 1, "definition_key": None}),
        (
            "reports",
            {
                "key_version": 1,
                "definition_key": NATIONAL_KEY,
                "dataset_independent_key": None,
            },
        ),
        (
            "reports",
            {
                "key_version": None,
                "definition_key": None,
                "dataset_independent_key": DATASET_INDEPENDENT_KEY,
            },
        ),
        (
            "reports",
            {
                "key_version": 1,
                "definition_key": NATIONAL_KEY,
                "dataset_independent_key": DATASET_INDEPENDENT_KEY.upper(),
            },
        ),
    ],
)
def test_a_malformed_or_incomplete_key_is_refused(
    session: Session,
    public_api_rows: PublicApiRows,
    table: str,
    key_columns: dict[str, object],
) -> None:
    columns: dict[str, object] = (
        {
            "simulation_type": "economy",
            "dataset_id": public_api_rows.dataset_id,
            "tax_benefit_model_version_id": public_api_rows.version_id,
        }
        if table == "simulations"
        else {
            "label": "Report",
            "country": "us",
            "tax_benefit_model_id": public_api_rows.model_id,
            "inputs": {},
        }
    )
    columns |= {"id": uuid4(), "year": 2026, **key_columns}

    with refused(session, IntegrityError, match="violates check constraint"):
        add_row(session, KEYED_MODELS[table], **columns)


def test_a_simulation_has_one_unfailed_unforced_run_per_version_set(
    session: Session, managed_v2_roles: ManagedV2Roles, public_api_rows: PublicApiRows
) -> None:
    simulation_id = _simulation(session, public_api_rows, NATIONAL_KEY)
    act_as(session, managed_v2_roles.simulation_service)

    first_run = _simulation_run(session, public_api_rows, simulation_id)
    joined = _simulation_run(session, public_api_rows, simulation_id)
    forced_run = _simulation_run(session, public_api_rows, simulation_id, forced=True)
    second_forced_run = _simulation_run(
        session, public_api_rows, simulation_id, forced=True
    )
    newer_versions_run = _simulation_run(
        session, public_api_rows, simulation_id, versions=NEWER_VERSIONS
    )
    other_year_run = _simulation_run(session, public_api_rows, simulation_id, year=2027)

    assert first_run is not None
    assert joined is None
    assert None not in {forced_run, second_forced_run, newer_versions_run}
    assert other_year_run is not None
    # Today's plain INSERT of a second run on the same versions is refused.
    _refused(
        session,
        insert(SimulationRun).values(
            id=uuid4(),
            simulation_id=simulation_id,
            year=2026,
            tax_benefit_model_version_id=public_api_rows.version_id,
            status="pending",
            **RUN_VERSIONS,
        ),
        match="uq_simulation_runs_unfailed_unforced_versions",
    )

    # A failed run never counts: the next request creates a new run.
    act_as(session, managed_v2_roles.modal_worker)
    _fail(session, SimulationRun, first_run)
    act_as(session, managed_v2_roles.simulation_service)
    after_failure = _simulation_run(session, public_api_rows, simulation_id)
    assert after_failure not in {None, first_run}
    # The failed run can't count again while the new one hasn't failed.
    act_as(session, managed_v2_roles.modal_worker)
    _refused(
        session,
        update_row(SimulationRun, first_run, status="running"),
        match="uq_simulation_runs_unfailed_unforced_versions",
    )


def test_a_report_has_one_unfailed_unforced_run_per_version_set_outside_windows(
    session: Session, managed_v2_roles: ManagedV2Roles, public_api_rows: PublicApiRows
) -> None:
    simulation_id = _simulation(session, public_api_rows, NATIONAL_KEY)
    report_id = _report(session, public_api_rows)
    act_as(session, managed_v2_roles.simulation_service)
    baseline_run_id = _simulation_run(session, public_api_rows, simulation_id)
    assert baseline_run_id is not None

    first_run = _report_run(session, report_id, baseline_run_id)
    joined = _report_run(session, report_id, baseline_run_id)
    forced_run = _report_run(session, report_id, baseline_run_id, forced=True)
    newer_versions_run = _report_run(
        session, report_id, baseline_run_id, versions=NEWER_VERSIONS
    )
    # Each window run names a report run per year on the same versions.
    for window_run_id in (uuid4(), uuid4()):
        add_row(
            session,
            BudgetWindowRun,
            id=window_run_id,
            report_id=report_id,
            tax_benefit_model_version_id=public_api_rows.version_id,
            recalculate=False,
            status="pending",
        )
        add_row(
            session,
            ReportRun,
            id=uuid4(),
            report_id=report_id,
            budget_window_run_id=window_run_id,
            year=2026,
            baseline_simulation_run_id=baseline_run_id,
            status="pending",
            **RUN_VERSIONS,
        )

    assert first_run is not None
    assert joined is None
    assert None not in {forced_run, newer_versions_run}
    act_as(session, managed_v2_roles.modal_worker)
    _fail(session, ReportRun, first_run)
    act_as(session, managed_v2_roles.simulation_service)
    assert _report_run(session, report_id, baseline_run_id) not in {
        None,
        first_run,
    }


def test_a_budget_window_has_one_unfailed_unrecalculated_run_per_version_set(
    session: Session, managed_v2_roles: ManagedV2Roles, public_api_rows: PublicApiRows
) -> None:
    """``recalculate`` is a window run's forced marker."""
    report_id = _report(session, public_api_rows)
    act_as(session, managed_v2_roles.simulation_service)

    def window_run(
        *, policyengine_version: str = "4.0.0", recalculate: bool = False
    ) -> UUID | None:
        return _inserted_id(
            session,
            _find_or_create_window_run(
                public_api_rows,
                report_id,
                policyengine_version=policyengine_version,
                recalculate=recalculate,
            ),
        )

    first_run = window_run()
    joined = window_run()
    recalculated = window_run(recalculate=True)
    newer_versions_run = window_run(policyengine_version="4.1.0")

    assert first_run is not None
    assert joined is None
    assert None not in {recalculated, newer_versions_run}
    act_as(session, managed_v2_roles.modal_worker)
    _fail(session, BudgetWindowRun, first_run)
    act_as(session, managed_v2_roles.simulation_service)
    assert window_run() not in {None, first_run}
    _refused(
        session,
        update_row(BudgetWindowRun, first_run, policyengine_version="4.9.9"),
        ProgrammingError,
        match="permission denied",
    )


def test_the_simulation_service_writes_shared_rows_without_per_user_columns(
    session: Session, managed_v2_roles: ManagedV2Roles, public_api_rows: PublicApiRows
) -> None:
    """A report without a label, and runs without a trigger, are stored as such."""
    simulation_id = _simulation(session, public_api_rows, NATIONAL_KEY)
    act_as(session, managed_v2_roles.simulation_service)
    baseline_run_id = _simulation_run(session, public_api_rows, simulation_id)
    report_id, report_run_id, window_run_id = uuid4(), uuid4(), uuid4()

    add_row(
        session,
        Report,
        id=report_id,
        country="us",
        tax_benefit_model_id=public_api_rows.model_id,
        year=2026,
        inputs={},
    )
    add_row(
        session,
        ReportRun,
        id=report_run_id,
        report_id=report_id,
        baseline_simulation_run_id=baseline_run_id,
        status="pending",
        **RUN_VERSIONS,
    )
    add_row(
        session,
        BudgetWindowRun,
        id=window_run_id,
        report_id=report_id,
        tax_benefit_model_version_id=public_api_rows.version_id,
        recalculate=False,
        status="pending",
    )

    act_as(session, managed_v2_roles.runtime)
    stored = session.execute(
        select(col(Report.label), col(ReportRun.trigger), col(BudgetWindowRun.trigger))
        .select_from(Report)
        .join(ReportRun, col(ReportRun.report_id) == col(Report.id))
        .join(BudgetWindowRun, col(BudgetWindowRun.report_id) == col(Report.id))
        .where(col(Report.id) == report_id)
    ).one()
    assert tuple(stored) == (None, None, None)


def test_no_simulation_role_changes_a_rows_key_or_a_runs_forced_marker(
    session: Session, managed_v2_roles: ManagedV2Roles, public_api_rows: PublicApiRows
) -> None:
    simulation_id = _simulation(session, public_api_rows, NATIONAL_KEY)
    report_id = _report(session, public_api_rows)
    act_as(session, managed_v2_roles.simulation_service)
    run_id = _simulation_run(session, public_api_rows, simulation_id)
    assert run_id is not None
    report_run_id = _report_run(session, report_id, run_id)

    for role in (
        managed_v2_roles.simulation_service,
        managed_v2_roles.modal_worker,
    ):
        act_as(session, role)
        # The keys' UPDATEs set only the key column: neither role may update
        # ``updated_at`` on simulations or reports, which the models' UPDATE
        # also sets. Both roles may update it on the run tables.
        for statement in (
            update_row(SimulationColumns, simulation_id, definition_key=None),
            update_row(ReportColumns, report_id, key_version=1),
            update_row(SimulationRun, run_id, forced=True),
            update_row(ReportRun, report_run_id, forced=True),
        ):
            _refused(session, statement, ProgrammingError, match="permission denied")


def test_the_public_api_records_each_users_request_for_a_report_run(
    session: Session, managed_v2_roles: ManagedV2Roles, public_api_rows: PublicApiRows
) -> None:
    simulation_id = _simulation(session, public_api_rows, NATIONAL_KEY)
    report_id = _report(session, public_api_rows)
    first_user, second_user, third_user = (_user(session) for _ in range(3))
    act_as(session, managed_v2_roles.simulation_service)
    baseline_run_id = _simulation_run(session, public_api_rows, simulation_id)
    report_run_id = _report_run(session, report_id, baseline_run_id)
    act_as(session, managed_v2_roles.runtime)

    first_record, second_record = uuid4(), uuid4()
    session.execute(
        _record_request(first_user, report_run_id, "initial", record_id=first_record)
    )
    # A second user who joins the same run gets a record of their own.
    session.execute(
        _record_request(second_user, report_run_id, "manual", record_id=second_record)
    )
    requesters = session.execute(
        select(col(UserReportRunAssociation.user_id))
        .where(col(UserReportRunAssociation.report_run_id) == report_run_id)
        .order_by(col(UserReportRunAssociation.trigger))
    ).scalars()
    assert list(requesters) == [first_user, second_user]
    _refused(
        session,
        _record_request(first_user, report_run_id, "manual"),
        match="uq_user_report_run_associations_user_id_report_run_id",
    )
    # A system re-run is nobody's request.
    _refused(
        session,
        _record_request(third_user, report_run_id, "system"),
        match="ck_user_report_run_associations_trigger",
    )
    _refused(
        session,
        update_row(UserReportRunAssociation, first_record, requested_at=func.now()),
        ProgrammingError,
        match="permission denied",
    )
    deleted = session.execute(
        delete(UserReportRunAssociation)
        .where(col(UserReportRunAssociation.id) == second_record)
        .returning(col(UserReportRunAssociation.id))
    ).scalar_one()
    assert deleted == second_record

    for role in (managed_v2_roles.simulation_service, managed_v2_roles.modal_worker):
        act_as(session, role)
        _refused(
            session,
            select(func.count()).select_from(UserReportRunAssociation),
            ProgrammingError,
            match="permission denied",
        )

    # A run a user asked for stays; the user's records go with the user.
    act_as_owner(session)
    _refused(
        session,
        delete(ReportRun).where(col(ReportRun.id) == report_run_id),
        match="fk_user_report_run_associations_report_run_id_report_runs",
    )
    session.execute(delete(User).where(col(User.id) == first_user))
    remaining = session.execute(
        select(func.count()).select_from(UserReportRunAssociation)
    ).scalar_one()
    assert remaining == 0

"""Run the simulation tables' writes as the roles that do them in production.

The simulation service creates simulations, reports, their runs, budget-window
runs, household jobs and simulation runs' cliff calculations; its Modal
workers write their runs' and cliff calculations' status and results and
their budget-window runs' status; API v1 reads them. Each
role holds only its declared privileges
(``policyengine_api/data/v2/privileges.py``), so a statement outside them
fails here as it would in staging and production.

Every statement runs through one Session of the database's owner, which
``act_as`` switches to a role for the rest of its transaction. An ORM
``update`` also sets ``updated_at`` on the tables that have it, which every
role here that updates those tables may do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import bindparam, delete, false, func, insert, inspect, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import ProgrammingError
from sqlmodel import col

from policyengine_api.constants import REPO
from policyengine_api.data.v2.models import (
    BudgetWindowRun,
    CliffImpact,
    Household,
    HouseholdJob,
    LaborSupplyDecileResponse,
    ParameterValue,
    Policy,
    Poverty,
    Report,
    ReportRun,
    Simulation,
    SimulationRun,
    SimulationStatus,
    WithheldAreaCode,
)
from policyengine_api.data.v2.privileges import (
    CATALOG_WRITER_ROLE,
    ColumnPrivilege,
    TablePrivilege,
    declared_privileges,
)
from tests.fixtures.database_sessions import act_as
from tests.integration.simulation_rows import (
    RUN_VERSIONS,
    PublicApiRows,
    add_row,
    insert_public_api_rows,
    refused,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Executable, Update
    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

    from tests.integration.conftest import ManagedV2Roles


@pytest.fixture
def session(
    v2_owner_sessions: sessionmaker[Session], managed_v2_roles: ManagedV2Roles
) -> Iterator[Session]:
    """Yield a Session at head whose writes are rolled back after the test.

    It acts as the disposable database's owner (superuser); ``act_as``
    switches it to one managed role for the rest of the transaction.
    """
    command.upgrade(Config(str(REPO / "alembic-v2.ini")), "head")
    with v2_owner_sessions() as owner_session:
        try:
            yield owner_session
        finally:
            owner_session.rollback()


@pytest.fixture
def public_api_rows(session: Session) -> PublicApiRows:
    """Store, as the owner, API v1's rows the simulation rows name."""
    return insert_public_api_rows(session)


def _refused(session: Session, statement: Executable) -> None:
    """Expect a permission error from ``statement``."""
    with refused(session, ProgrammingError, match="permission denied"):
        session.execute(statement)


def _update_row(model: type[Any], row_id: object, **values: object) -> Update:
    """Build an UPDATE of the model's row with ID ``row_id``, setting ``values``."""
    return update(model).where(model.id == row_id).values(**values)


def _update_from_status(
    session: Session,
    model: type[Any],
    row_id: object,
    current_status: str,
    **values: object,
) -> object:
    """Update the row while its status is ``current_status``, as the services do.

    Return its ID, from the statement's RETURNING, which expects exactly the
    one row.
    """
    return session.execute(
        update(model)
        .where(model.id == row_id, model.status == current_status)
        .values(**values)
        .returning(model.id)
    ).scalar_one()


def _row_count(model: type[Any], *conditions: Any) -> Executable:
    """Build a count of the model's rows that meet ``conditions``."""
    return select(func.count()).select_from(model).where(*conditions)


def _create_simulation_rows(
    session: Session, public_api_rows: PublicApiRows
) -> dict[str, UUID]:
    """Create what the simulation API creates for one economy report run."""
    ids = {
        name: uuid4()
        for name in (
            "simulation",
            "run",
            "report",
            "budget_window_run",
            "report_run",
            "household_job",
        )
    }
    add_row(
        session,
        Simulation,
        id=ids["simulation"],
        simulation_type="economy",
        dataset_id=public_api_rows.dataset_id,
        tax_benefit_model_version_id=public_api_rows.version_id,
        year=2026,
    )
    add_row(
        session,
        SimulationRun,
        id=ids["run"],
        simulation_id=ids["simulation"],
        tax_benefit_model_version_id=public_api_rows.version_id,
        year=2026,
        status="pending",
        **RUN_VERSIONS,
    )
    add_row(
        session,
        Report,
        id=ids["report"],
        label="Report",
        country="us",
        tax_benefit_model_id=public_api_rows.model_id,
        year=2026,
        budget_window_size=1,
        inputs={},
    )
    add_row(
        session,
        BudgetWindowRun,
        id=ids["budget_window_run"],
        report_id=ids["report"],
        tax_benefit_model_version_id=public_api_rows.version_id,
        trigger="initial",
        recalculate=False,
        status="pending",
    )
    add_row(
        session,
        ReportRun,
        id=ids["report_run"],
        report_id=ids["report"],
        budget_window_run_id=ids["budget_window_run"],
        year=2026,
        baseline_simulation_run_id=ids["run"],
        status="pending",
        trigger="initial",
        **RUN_VERSIONS,
    )
    add_row(
        session,
        HouseholdJob,
        id=ids["household_job"],
        country="us",
        household_id=public_api_rows.household_id,
        year=2026,
        request_data={},
        tax_benefit_model_version_id=public_api_rows.version_id,
        status="pending",
        **RUN_VERSIONS,
    )
    return ids


def test_the_simulation_service_creates_rows_and_records_only_its_calls(
    session: Session, managed_v2_roles: ManagedV2Roles, public_api_rows: PublicApiRows
) -> None:
    act_as(session, managed_v2_roles.simulation_service)

    ids = _create_simulation_rows(session, public_api_rows)
    run_count = session.execute(
        _row_count(SimulationRun, col(SimulationRun.id) == ids["run"])
    ).scalar_one()
    session.execute(_row_count(Policy)).scalar_one()

    assert run_count == 1
    # The service records a Modal call's ID once Modal accepts the call, and
    # fails the run when Modal refuses it, while the run is still pending.
    recorded = session.execute(
        update(ReportRun)
        .where(
            col(ReportRun.id) == ids["report_run"],
            col(ReportRun.status) == "pending",
            col(ReportRun.modal_call_id).is_(None),
        )
        .values(modal_call_id="fc-accepted", updated_at=func.now())
        .returning(col(ReportRun.id))
    ).scalar_one()
    failed = _update_from_status(
        session,
        HouseholdJob,
        ids["household_job"],
        "pending",
        status="failed",
        error_message="refused",
        completed_at=func.now(),
        updated_at=func.now(),
    )
    assert (recorded, failed) == (ids["report_run"], ids["household_job"])
    for statement in (
        _update_row(SimulationRun, ids["run"], started_at=func.now()),
        _update_row(SimulationRun, ids["run"], output_uri="gs://bucket/run"),
        _update_row(SimulationRun, ids["run"], year=2027),
        _update_row(ReportRun, ids["report_run"], baseline_cliff_gap=1.0),
        insert(Poverty).values(
            id=uuid4(),
            simulation_run_id=ids["run"],
            poverty_type="spm",
            entity="person",
        ),
        delete(Simulation).where(col(Simulation.id) == ids["simulation"]),
        insert(LaborSupplyDecileResponse).values(
            id=uuid4(), report_run_id=ids["report_run"], decile=1
        ),
        update(Policy).values(content_hash=col(Policy.content_hash)),
    ):
        _refused(session, statement)


def test_modal_workers_write_their_run_status_and_results_only(
    session: Session, managed_v2_roles: ManagedV2Roles, public_api_rows: PublicApiRows
) -> None:
    act_as(session, managed_v2_roles.simulation_service)
    ids = _create_simulation_rows(session, public_api_rows)
    act_as(session, managed_v2_roles.modal_worker)

    updated = _update_from_status(
        session,
        SimulationRun,
        ids["run"],
        "pending",
        status="succeeded",
        completed_at=func.now(),
    )
    add_row(
        session,
        Poverty,
        id=uuid4(),
        simulation_run_id=ids["run"],
        poverty_type="spm",
        entity="person",
        rate=0.1,
    )
    session.execute(
        _update_row(
            ReportRun,
            ids["report_run"],
            status="running",
            started_at=func.now(),
            modal_call_id="fc-coordinator",
            baseline_cliff_gap=1.0,
            baseline_cliff_share=0.1,
            reform_cliff_gap=2.0,
            reform_cliff_share=0.2,
            data_version="1.0.0",
            spm_provenance={},
            updated_at=func.now(),
        )
    )
    add_row(
        session,
        LaborSupplyDecileResponse,
        id=uuid4(),
        report_run_id=ids["report_run"],
        decile=1,
        average_income_effect=-1.0,
    )
    finished_job = _update_from_status(
        session,
        HouseholdJob,
        ids["household_job"],
        "pending",
        status="succeeded",
        result={},
        completed_at=func.now(),
    )
    session.execute(_row_count(ParameterValue)).scalar_one()

    assert updated == ids["run"]
    assert finished_job == ids["household_job"]
    for statement in (
        insert(Simulation).values(
            id=uuid4(),
            simulation_type="economy",
            dataset_id=uuid4(),
            tax_benefit_model_version_id=uuid4(),
        ),
        delete(Poverty).where(col(Poverty.simulation_run_id) == ids["run"]),
        insert(BudgetWindowRun).values(
            id=uuid4(),
            report_id=ids["report"],
            tax_benefit_model_version_id=public_api_rows.version_id,
            trigger="manual",
            recalculate=True,
            status="pending",
        ),
        update(Poverty)
        .where(col(Poverty.simulation_run_id) == ids["run"])
        .values(rate=0),
        update(Household).values(content_hash=col(Household.content_hash)),
    ):
        _refused(session, statement)
    # What a run is stays as the simulation service wrote it.
    for statement in (
        _update_row(SimulationRun, ids["run"], year=2027),
        _update_row(
            SimulationRun, ids["run"], simulation_id=col(SimulationRun.simulation_id)
        ),
        _update_row(
            ReportRun,
            ids["report_run"],
            baseline_simulation_run_id=col(ReportRun.baseline_simulation_run_id),
        ),
        _update_row(ReportRun, ids["report_run"], markdown="edited"),
        _update_row(
            HouseholdJob,
            ids["household_job"],
            household_id=col(HouseholdJob.household_id),
        ),
    ):
        _refused(session, statement)


def test_modal_workers_insert_withheld_area_codes_that_the_public_api_reads(
    session: Session, managed_v2_roles: ManagedV2Roles, public_api_rows: PublicApiRows
) -> None:
    """The workers insert and read the rows, API v1 only reads them.

    The simulation service, the Stage 12 role and the catalog writer can't read
    them.
    """
    act_as(session, managed_v2_roles.simulation_service)
    ids = _create_simulation_rows(session, public_api_rows)
    act_as(session, managed_v2_roles.modal_worker)
    withheld_code_id = uuid4()

    add_row(
        session,
        WithheldAreaCode,
        id=withheld_code_id,
        report_run_id=ids["report_run"],
        baseline_simulation_run_id=ids["run"],
        reform_simulation_run_id=ids["run"],
        area_type="constituency",
        code="E14001063",
    )
    assert (
        session.execute(
            _row_count(
                WithheldAreaCode,
                col(WithheldAreaCode.report_run_id) == ids["report_run"],
            )
        ).scalar_one()
        == 1
    )

    # Once written, a withheld code is never changed or removed by the workers.
    _refused(session, _update_row(WithheldAreaCode, withheld_code_id, code="E14001064"))
    _refused(
        session,
        delete(WithheldAreaCode).where(col(WithheldAreaCode.id) == withheld_code_id),
    )
    act_as(session, managed_v2_roles.runtime)
    assert (
        session.execute(
            select(col(WithheldAreaCode.code)).where(
                col(WithheldAreaCode.id) == withheld_code_id
            )
        ).scalar_one()
        == "E14001063"
    )
    _refused(
        session,
        insert(WithheldAreaCode).values(
            id=uuid4(),
            report_run_id=ids["report_run"],
            baseline_simulation_run_id=ids["run"],
            reform_simulation_run_id=ids["run"],
            area_type="constituency",
            code="E14001064",
        ),
    )
    for role in (
        managed_v2_roles.simulation_service,
        managed_v2_roles.stage12,
        CATALOG_WRITER_ROLE,
    ):
        act_as(session, role)
        _refused(session, _row_count(WithheldAreaCode))


def test_the_simulation_service_fails_a_window_whose_first_calls_modal_refuses(
    session: Session, managed_v2_roles: ManagedV2Roles, public_api_rows: PublicApiRows
) -> None:
    """The service fails a budget-window run when Modal refuses its first years.

    It never sets when the window started, which the Modal workers record, and
    never changes what the window is.
    """
    act_as(session, managed_v2_roles.simulation_service)
    ids = _create_simulation_rows(session, public_api_rows)
    window_id = ids["budget_window_run"]

    failed_window = _update_from_status(
        session,
        BudgetWindowRun,
        window_id,
        "pending",
        status="failed",
        error_message="refused",
        completed_at=func.now(),
        updated_at=func.now(),
    )

    assert failed_window == window_id
    for statement in (
        _update_row(BudgetWindowRun, window_id, started_at=func.now()),
        _update_row(BudgetWindowRun, window_id, recalculate=True),
        _update_row(
            BudgetWindowRun, window_id, report_id=col(BudgetWindowRun.report_id)
        ),
    ):
        _refused(session, statement)


def test_modal_workers_start_finish_and_fail_budget_windows(
    session: Session, managed_v2_roles: ManagedV2Roles, public_api_rows: PublicApiRows
) -> None:
    """The Modal workers write a budget-window run's status and times.

    Each year's coordinator starts the window's next unstarted year when its
    own year finishes; the last year to finish marks the window succeeded, and
    a failed year fails it.
    """
    act_as(session, managed_v2_roles.simulation_service)
    ids = _create_simulation_rows(session, public_api_rows)
    window_id = ids["budget_window_run"]
    failing_window_id = uuid4()
    add_row(
        session,
        BudgetWindowRun,
        id=failing_window_id,
        report_id=ids["report"],
        tax_benefit_model_version_id=public_api_rows.version_id,
        trigger="manual",
        recalculate=True,
        status="pending",
    )
    act_as(session, managed_v2_roles.modal_worker)

    started_windows = [
        _update_from_status(
            session,
            BudgetWindowRun,
            started_window_id,
            "pending",
            status="running",
            started_at=func.now(),
            updated_at=func.now(),
        )
        for started_window_id in (window_id, failing_window_id)
    ]
    succeeded_window = _update_from_status(
        session,
        BudgetWindowRun,
        window_id,
        "running",
        status="succeeded",
        completed_at=func.now(),
        updated_at=func.now(),
    )
    failed_window = _update_from_status(
        session,
        BudgetWindowRun,
        failing_window_id,
        "running",
        status="failed",
        error_message="the 2027 report run failed",
        completed_at=func.now(),
        updated_at=func.now(),
    )

    assert started_windows == [window_id, failing_window_id]
    assert (succeeded_window, failed_window) == (window_id, failing_window_id)
    for statement in (
        _update_row(BudgetWindowRun, window_id, trigger="manual"),
        _update_row(BudgetWindowRun, window_id, recalculate=False),
        _update_row(
            BudgetWindowRun,
            window_id,
            tax_benefit_model_version_id=col(
                BudgetWindowRun.tax_benefit_model_version_id
            ),
        ),
    ):
        _refused(session, statement)


@pytest.mark.parametrize("role_kind", ["simulation_service", "modal_worker"])
def test_each_simulation_role_locks_a_budget_window_run_row(
    session: Session,
    managed_v2_roles: ManagedV2Roles,
    public_api_rows: PublicApiRows,
    role_kind: str,
) -> None:
    """Either role may lock a window's row, for example before changing its status.

    PostgreSQL lets a role lock a row ``FOR UPDATE`` when it may update some of
    the table's columns. A lock over a join with ``reports`` names
    ``budget_window_runs`` alone: neither role may update ``reports``, so a lock
    on every joined table is refused.
    """
    act_as(session, managed_v2_roles.simulation_service)
    ids = _create_simulation_rows(session, public_api_rows)
    act_as(session, getattr(managed_v2_roles, role_kind))
    is_the_window = col(BudgetWindowRun.id) == ids["budget_window_run"]
    report_of_the_window = col(Report.id) == col(BudgetWindowRun.report_id)

    locked_window = session.execute(
        select(col(BudgetWindowRun.id)).where(is_the_window).with_for_update()
    ).scalar_one()
    locked_over_join = session.execute(
        select(col(BudgetWindowRun.id), col(Report.budget_window_size))
        .join(Report, report_of_the_window)
        .where(is_the_window)
        .with_for_update(of=BudgetWindowRun)
    ).one()

    assert locked_window == ids["budget_window_run"]
    assert tuple(locked_over_join) == (ids["budget_window_run"], 1)
    _refused(
        session,
        select(col(BudgetWindowRun.id))
        .join(Report, report_of_the_window)
        .where(is_the_window)
        .with_for_update(),
    )


def test_the_public_api_reads_runs_and_results_but_writes_neither(
    session: Session, managed_v2_roles: ManagedV2Roles
) -> None:
    act_as(session, managed_v2_roles.runtime)

    for model in (SimulationRun, ReportRun, Poverty):
        session.execute(_row_count(model)).scalar_one()
    _refused(
        session,
        insert(ReportRun).values(
            id=uuid4(),
            report_id=uuid4(),
            baseline_simulation_run_id=uuid4(),
            country_package_version="1.0.0",
            policyengine_version="4.0.0",
            status="pending",
            trigger="initial",
        ),
    )


@pytest.mark.parametrize("role_kind", ["simulation_service", "modal_worker"])
def test_each_simulation_role_updates_exactly_its_declared_columns(
    session: Session, managed_v2_roles: ManagedV2Roles, role_kind: str
) -> None:
    """Every column of the run tables is updatable exactly when it is declared.

    Setting a column other than ``updated_at`` also sets ``updated_at``, which
    both roles may update on each of these tables.
    """
    role = getattr(managed_v2_roles, role_kind)
    declared = declared_privileges(managed_v2_roles.deployment_environment)[role]
    act_as(session, role)

    for model in (
        SimulationRun,
        ReportRun,
        HouseholdJob,
        BudgetWindowRun,
        CliffImpact,
    ):
        updatable = {
            column
            for privilege in declared[model.__tablename__]
            if isinstance(privilege, ColumnPrivilege)
            and privilege.privilege is TablePrivilege.UPDATE
            for column in privilege.columns
        }
        for column_attribute in inspect(model).column_attrs:
            column = getattr(model, column_attribute.key)
            # The privilege is checked when the statement starts, so no row is
            # needed.
            statement = update(model).where(false()).values({column: column})
            if column_attribute.key in updatable:
                session.execute(statement)
            else:
                _refused(session, statement)


def _start_cliff_calculation(session: Session, run_id: object) -> UUID | None:
    """Start the run's cliff calculation, unless one that hasn't failed exists.

    This is what the simulation service inserts; return the new calculation's
    ID, or None. Naming the partial unique index's conflict target needs SELECT
    as well as INSERT. Its condition is sent as a literal, as in the index, so
    PostgreSQL can match the index however often the statement runs.
    """
    unfailed = col(CliffImpact.status) != bindparam(
        "failed_status", SimulationStatus.FAILED, literal_execute=True
    )
    return session.execute(
        postgresql.insert(CliffImpact)
        .values(id=uuid4(), simulation_run_id=run_id, status="pending")
        .on_conflict_do_nothing(
            index_elements=[col(CliffImpact.simulation_run_id)],
            index_where=unfailed,
        )
        .returning(col(CliffImpact.id))
    ).scalar_one_or_none()


def test_the_simulation_service_starts_cliff_calculations_and_records_calls(
    session: Session, managed_v2_roles: ManagedV2Roles, public_api_rows: PublicApiRows
) -> None:
    """The service inserts a run's calculation once, and records or fails its call.

    It never claims a calculation, writes its numbers, changes the run it
    calculates or deletes it.
    """
    act_as(session, managed_v2_roles.simulation_service)
    ids = _create_simulation_rows(session, public_api_rows)

    calculation_id = _start_cliff_calculation(session, ids["run"])
    joined_calculation = _start_cliff_calculation(session, ids["run"])
    recorded = session.execute(
        update(CliffImpact)
        .where(
            col(CliffImpact.id) == calculation_id,
            col(CliffImpact.status) == "pending",
            col(CliffImpact.modal_call_id).is_(None),
        )
        .values(modal_call_id="fc-cliffs", updated_at=func.now())
        .returning(col(CliffImpact.id))
    ).scalar_one()
    failed = _update_from_status(
        session,
        CliffImpact,
        calculation_id,
        "pending",
        status="failed",
        error_message="modal_refused: refused",
        completed_at=func.now(),
        updated_at=func.now(),
    )

    assert calculation_id is not None
    assert joined_calculation is None
    assert recorded == failed == calculation_id
    for statement in (
        _update_row(CliffImpact, calculation_id, started_at=func.now()),
        _update_row(CliffImpact, calculation_id, cliff_gap=1.0),
        _update_row(
            CliffImpact,
            calculation_id,
            simulation_run_id=col(CliffImpact.simulation_run_id),
        ),
        delete(CliffImpact).where(col(CliffImpact.id) == calculation_id),
    ):
        _refused(session, statement)


def test_modal_workers_claim_cliff_calculations_and_write_their_results(
    session: Session, managed_v2_roles: ManagedV2Roles, public_api_rows: PublicApiRows
) -> None:
    """A worker claims a pending calculation under its call and finishes it.

    It never inserts a calculation, changes the run it calculates or deletes
    one.
    """
    act_as(session, managed_v2_roles.simulation_service)
    ids = _create_simulation_rows(session, public_api_rows)
    calculation_id = _start_cliff_calculation(session, ids["run"])
    act_as(session, managed_v2_roles.modal_worker)

    claimed = _update_from_status(
        session,
        CliffImpact,
        calculation_id,
        "pending",
        status="running",
        started_at=func.now(),
        modal_call_id="fc-cliffs",
        updated_at=func.now(),
    )
    succeeded = _update_from_status(
        session,
        CliffImpact,
        calculation_id,
        "running",
        status="succeeded",
        cliff_gap=1.5e9,
        cliff_share=0.04,
        completed_at=func.now(),
        updated_at=func.now(),
    )

    assert claimed == succeeded == calculation_id
    for statement in (
        insert(CliffImpact).values(
            id=uuid4(), simulation_run_id=ids["run"], status="pending"
        ),
        _update_row(
            CliffImpact,
            calculation_id,
            simulation_run_id=col(CliffImpact.simulation_run_id),
        ),
        delete(CliffImpact).where(col(CliffImpact.id) == calculation_id),
    ):
        _refused(session, statement)


def test_api_v1_reads_cliff_results_and_other_roles_cannot(
    session: Session, managed_v2_roles: ManagedV2Roles, public_api_rows: PublicApiRows
) -> None:
    """API v1 reads a report run's two cliff results and writes none.

    The catalog writer and the Stage 12 role can't read them.
    """
    act_as(session, managed_v2_roles.simulation_service)
    ids = _create_simulation_rows(session, public_api_rows)
    calculation_id = _start_cliff_calculation(session, ids["run"])
    act_as(session, managed_v2_roles.modal_worker)
    session.execute(
        _update_row(
            CliffImpact,
            calculation_id,
            status="succeeded",
            cliff_gap=1.5e9,
            cliff_share=0.04,
            completed_at=func.now(),
        )
    )
    act_as(session, managed_v2_roles.runtime)

    results = session.execute(
        select(col(CliffImpact.cliff_gap), col(CliffImpact.cliff_share))
        .select_from(ReportRun)
        .join(
            CliffImpact,
            col(CliffImpact.simulation_run_id).in_(
                [
                    col(ReportRun.baseline_simulation_run_id),
                    col(ReportRun.reform_simulation_run_id),
                ]
            ),
        )
        .where(
            col(ReportRun.id) == ids["report_run"],
            col(CliffImpact.status) == "succeeded",
        )
    ).all()

    assert [tuple(result) for result in results] == [(1.5e9, 0.04)]
    _refused(
        session,
        insert(CliffImpact).values(
            id=uuid4(), simulation_run_id=ids["run"], status="pending"
        ),
    )
    _refused(session, _update_row(CliffImpact, calculation_id, cliff_gap=0))
    for role in (managed_v2_roles.stage12, CATALOG_WRITER_ROLE):
        act_as(session, role)
        _refused(session, _row_count(CliffImpact))

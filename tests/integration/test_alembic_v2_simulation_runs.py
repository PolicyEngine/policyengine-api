"""Check the simulation runs revision against disposable Postgres.

One revision follows the catalog pruning revision. It adds simulation
runs, one per simulation and year; has each report run name its baseline and
reform simulation runs; keys every result table by run; types a report run's
cliff impact and labour supply; adds the budget-window tables; gives household
jobs one household, one year and one policy; and adds the economy output's
fields that had no column. The foreign keys from those tables to API v1's
tables stay, and the new columns that name API v1's rows get keys too. It
changes no other table. The previous API v1 revision keeps working while it
is deployed: its roles can't read or write any table it changes, except the
catalog writer, which counts the rows of simulations, reports and
report_runs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql.base import PGInspector
from sqlmodel import col

from policyengine_api.constants import REPO
from policyengine_api.data.v2.models import (
    BudgetSummary,
    BudgetWindowRun,
    ConstituencyImpact,
    DecileImpact,
    HouseholdJob,
    LaborSupplyDecileResponse,
    LaborSupplyResponse,
    Poverty,
    ProgramStatistics,
    Report,
    ReportRun,
    Simulation,
    SimulationRun,
)
from tests.fixtures.database_sessions import schema_inspector
from tests.fixtures.integration.alembic_v2 import table_columns
from tests.integration.simulation_rows import (
    RUN_VERSIONS,
    PublicApiRows,
    add_row,
    insert_public_api_rows,
    refused,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Inspector
    from sqlalchemy.orm import Mapped, sessionmaker
    from sqlmodel import Session

# The catalog pruning revision, the simulation runs revision's parent.
SIMULATION_RUNS_PREVIOUS_REVISION = "334859ef4fec"
SIMULATION_RUNS_REVISION = "1356f658347d"
NEW_TABLES = frozenset(
    {
        "simulation_runs",
        "budget_window_runs",
        "labor_supply_responses",
        "labor_supply_decile_responses",
    }
)
CHANGED_TABLES = frozenset(
    {
        "budget_summary",
        "congressional_district_impacts",
        "constituency_impacts",
        "decile_impacts",
        "household_jobs",
        "inequality",
        "intra_decile_impacts",
        "local_authority_impacts",
        "poverty",
        "program_statistics",
        "report_runs",
        "reports",
        "simulations",
    }
)
# The tables the simulation service and its Modal workers write; API v1
# writes every other table. withheld_area_codes and cliff_impacts came in later
# revisions.
SIMULATION_SIDE_TABLES = (
    CHANGED_TABLES
    | NEW_TABLES
    | {"aggregates", "change_aggregates", "withheld_area_codes", "cliff_impacts"}
)
# The foreign keys from the simulation service's tables to API v1's
# rows, with their delete rules.
PUBLIC_API_FOREIGN_KEYS = {
    ("simulations", "dataset_id"): ("datasets", "RESTRICT"),
    ("simulations", "household_id"): ("households", "RESTRICT"),
    ("simulations", "policy_id"): ("policies", "SET NULL"),
    ("simulations", "dynamic_id"): ("dynamics", "SET NULL"),
    ("simulations", "tax_benefit_model_version_id"): (
        "tax_benefit_model_versions",
        "RESTRICT",
    ),
    ("simulations", "region_id"): ("regions", "SET NULL"),
    ("reports", "user_id"): ("users", "SET NULL"),
    ("reports", "tax_benefit_model_id"): ("tax_benefit_models", "RESTRICT"),
    ("reports", "policy_id"): ("policies", "SET NULL"),
    ("reports", "household_id"): ("households", "RESTRICT"),
    ("reports", "dataset_id"): ("datasets", "SET NULL"),
    ("reports", "region_id"): ("regions", "SET NULL"),
    ("simulation_runs", "tax_benefit_model_version_id"): (
        "tax_benefit_model_versions",
        "RESTRICT",
    ),
    ("simulation_runs", "dataset_id"): ("datasets", "RESTRICT"),
    ("simulation_runs", "region_id"): ("regions", "SET NULL"),
    ("household_jobs", "household_id"): ("households", "RESTRICT"),
    ("household_jobs", "policy_id"): ("policies", "SET NULL"),
    ("household_jobs", "dynamic_id"): ("dynamics", "SET NULL"),
    ("household_jobs", "tax_benefit_model_version_id"): (
        "tax_benefit_model_versions",
        "RESTRICT",
    ),
    ("budget_window_runs", "tax_benefit_model_version_id"): (
        "tax_benefit_model_versions",
        "RESTRICT",
    ),
}
LABOR_SUPPLY_RESPONSE_COLUMNS = (
    "income_effect_earnings_change",
    "substitution_effect_earnings_change",
    "total_earnings_change",
    "revenue_change",
    "relative_income_effect",
    "relative_substitution_effect",
    "baseline_weekly_hours",
    "reform_weekly_hours",
    "weekly_hours_change",
    "weekly_hours_income_effect",
    "weekly_hours_substitution_effect",
)
SHA256_HEX = "a" * 64
COMPLETED_AT = datetime(2026, 11, 4, tzinfo=UTC)


@pytest.fixture
def config() -> Config:
    return Config(str(REPO / "alembic-v2.ini"))


@pytest.fixture
def sessions(
    config: Config, v2_owner_sessions: sessionmaker[Session]
) -> Iterator[sessionmaker[Session]]:
    """Yield the disposable database owner's Session factories; leave it at head."""
    try:
        yield v2_owner_sessions
    finally:
        command.upgrade(config, "head")


@pytest.fixture
def session(config: Config, sessions: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a Session at head whose writes are rolled back after the test."""
    command.upgrade(config, "head")
    with sessions() as database_session:
        try:
            yield database_session
        finally:
            database_session.rollback()


def _table_shape(inspector: Inspector, table_name: str) -> dict[str, object]:
    """Describe one table's columns, keys, indexes and checks for comparison."""
    return {
        "columns": [
            (column["name"], str(column["type"]), column["nullable"], column["default"])
            for column in inspector.get_columns(table_name)
        ],
        "primary_key": inspector.get_pk_constraint(table_name),
        "foreign_keys": sorted(
            inspector.get_foreign_keys(table_name), key=lambda key: str(key["name"])
        ),
        "indexes": sorted(
            inspector.get_indexes(table_name), key=lambda index: str(index["name"])
        ),
        "unique_constraints": sorted(
            inspector.get_unique_constraints(table_name),
            key=lambda constraint: str(constraint["name"]),
        ),
        "check_constraints": sorted(
            inspector.get_check_constraints(table_name),
            key=lambda constraint: str(constraint["name"]),
        ),
    }


def _shapes(sessions: sessionmaker[Session]) -> dict[str, dict[str, object]]:
    with sessions() as session:
        inspector = schema_inspector(session)
        return {
            table_name: _table_shape(inspector, table_name)
            for table_name in inspector.get_table_names(schema="public")
        }


def _column_names(sessions: sessionmaker[Session], table_name: str) -> set[str]:
    return set(table_columns(sessions, table_name))


def _enum_type_names(sessions: sessionmaker[Session]) -> set[str]:
    """Return the name of every enum type, in every schema."""
    inspector = schema_inspector(sessions)
    assert isinstance(inspector, PGInspector)
    return {enum_type["name"] for enum_type in inspector.get_enums(schema="*")}


def test_the_revision_downgrades_to_its_parent_and_upgrades_again(
    config: Config, sessions: sessionmaker[Session]
) -> None:
    """The revision adds its tables and changes only simulation-side tables."""
    command.upgrade(config, "head")

    command.downgrade(config, SIMULATION_RUNS_PREVIOUS_REVISION)
    before = _shapes(sessions)
    assert NEW_TABLES.isdisjoint(before)
    assert {"status", "household_result", "output_dataset_id"} <= _column_names(
        sessions, "simulations"
    )
    assert {"report_run_id", "simulation_id"} <= _column_names(sessions, "poverty")
    assert {"datasets", "households", "policies"} <= {
        key["referred_table"]
        for key in schema_inspector(sessions).get_foreign_keys("simulations")
    }
    program_entity = table_columns(sessions, "program_statistics")["entity"]
    assert not program_entity["nullable"]
    assert "v2_simulation_status" in _enum_type_names(sessions)

    # Upgrade to this revision alone: later revisions change other tables.
    command.upgrade(config, SIMULATION_RUNS_REVISION)
    after = _shapes(sessions)
    command.upgrade(config, "head")
    command.check(config)
    assert set(after) - set(before) == NEW_TABLES
    assert set(before) <= set(after)
    changed = {
        table_name for table_name in before if before[table_name] != after[table_name]
    }
    assert changed == CHANGED_TABLES
    assert {"baseline_simulation_run_id", "reform_simulation_run_id"} <= (
        _column_names(sessions, "report_runs")
    )


def test_head_keeps_the_foreign_keys_to_the_public_api_tables(
    config: Config, sessions: sessionmaker[Session]
) -> None:
    """Each service writes only its own tables; the keys between them stay."""
    command.upgrade(config, "head")
    inspector = schema_inspector(sessions)

    public_api_keys = {
        (table_name, column_name): (key["referred_table"], key["options"]["ondelete"])
        for table_name in SIMULATION_SIDE_TABLES
        for key in inspector.get_foreign_keys(table_name)
        if key["referred_table"] not in SIMULATION_SIDE_TABLES
        for column_name in key["constrained_columns"]
    }

    assert public_api_keys == PUBLIC_API_FOREIGN_KEYS
    assert {"ix_reports_user_id"} <= {
        index["name"] for index in inspector.get_indexes("reports")
    }


def _count(session: Session, column: Mapped[Any], value: object) -> int:
    """Count the rows whose ``column`` holds ``value``."""
    return session.scalars(select(func.count()).where(column == value)).one()


@pytest.fixture
def public_api_rows(session: Session) -> PublicApiRows:
    return insert_public_api_rows(session)


def _insert_simulation(session: Session, public_api_rows: PublicApiRows) -> UUID:
    """Store an economy simulation of the stored dataset and catalog version."""
    simulation_id = uuid4()
    add_row(
        session,
        Simulation,
        id=simulation_id,
        simulation_type="economy",
        dataset_id=public_api_rows.dataset_id,
        tax_benefit_model_version_id=public_api_rows.version_id,
        year=2026,
    )
    return simulation_id


def _insert_simulation_run(
    session: Session,
    simulation_id: UUID,
    *,
    status: str = "pending",
    year: int = 2026,
    **values: object,
) -> UUID:
    """Store a run of the simulation for ``year`` on its catalog version."""
    run_id = uuid4()
    version_id = session.scalars(
        select(col(Simulation.tax_benefit_model_version_id)).where(
            col(Simulation.id) == simulation_id
        )
    ).one()
    add_row(
        session,
        SimulationRun,
        id=run_id,
        simulation_id=simulation_id,
        tax_benefit_model_version_id=version_id,
        status=status,
        year=year,
        **RUN_VERSIONS,
        **values,
    )
    return run_id


def _insert_report_run(
    session: Session,
    public_api_rows: PublicApiRows,
    baseline_run_id: UUID | None,
    reform_run_id: UUID | None = None,
) -> UUID:
    """Store a report and one run of it comparing the two simulation runs."""
    report_id, report_run_id = uuid4(), uuid4()
    add_row(
        session,
        Report,
        id=report_id,
        label="Report",
        country="us",
        tax_benefit_model_id=public_api_rows.model_id,
        inputs={},
    )
    add_row(
        session,
        ReportRun,
        id=report_run_id,
        report_id=report_id,
        baseline_simulation_run_id=baseline_run_id,
        reform_simulation_run_id=reform_run_id,
        status="running",
        trigger="initial",
        **RUN_VERSIONS,
    )
    return report_run_id


def _update_simulation_run(session: Session, run_id: UUID, **values: object) -> None:
    session.execute(
        update(SimulationRun).where(col(SimulationRun.id) == run_id).values(**values)
    )


def _update_report_run(session: Session, report_run_id: UUID, **values: object) -> None:
    session.execute(
        update(ReportRun).where(col(ReportRun.id) == report_run_id).values(**values)
    )


def test_rows_naming_a_missing_public_api_row_are_refused(
    session: Session, public_api_rows: PublicApiRows
) -> None:
    """PostgreSQL checks each row a simulation-side row names when it is written."""
    simulation_id = _insert_simulation(session, public_api_rows)

    with refused(session, match="foreign key constraint"):
        add_row(
            session,
            SimulationRun,
            id=uuid4(),
            simulation_id=simulation_id,
            tax_benefit_model_version_id=uuid4(),
            status="pending",
            year=2026,
            **RUN_VERSIONS,
        )
    with refused(session, match="foreign key constraint"):
        add_row(
            session,
            HouseholdJob,
            id=uuid4(),
            country="us",
            household_id=uuid4(),
            year=2026,
            request_data={},
            tax_benefit_model_version_id=public_api_rows.version_id,
            status="pending",
            **RUN_VERSIONS,
        )


def test_simulation_runs_need_a_completion_time_and_a_whole_output(
    session: Session, public_api_rows: PublicApiRows
) -> None:
    simulation_id = _insert_simulation(session, public_api_rows)
    run_id = _insert_simulation_run(session, simulation_id)

    with refused(session):
        _update_simulation_run(session, run_id, status="succeeded")
    # Named, since a second unfailed run on the same versions is refused too.
    with refused(session, match="ck_simulation_runs_output_pair"):
        _insert_simulation_run(
            session, simulation_id, output_uri="gs://bucket/run.parquet"
        )
    with refused(session, match="ck_simulation_runs_output_sha256_length"):
        _insert_simulation_run(
            session,
            simulation_id,
            output_uri="gs://bucket/run.parquet",
            output_sha256="short",
        )
    # A simulation has one unfailed run per version set, so the run finishes.
    _update_simulation_run(
        session,
        run_id,
        status="succeeded",
        completed_at=COMPLETED_AT,
        output_uri="gs://bucket/run.parquet",
        output_sha256=SHA256_HEX,
    )
    add_row(
        session,
        Poverty,
        id=uuid4(),
        simulation_run_id=run_id,
        poverty_type="spm",
        entity="person",
    )

    session.execute(delete(Simulation).where(col(Simulation.id) == simulation_id))
    assert _count(session, col(SimulationRun.simulation_id), simulation_id) == 0
    assert _count(session, col(Poverty.simulation_run_id), run_id) == 0


def test_report_runs_name_a_baseline_run_and_keep_their_simulation_runs(
    session: Session, public_api_rows: PublicApiRows
) -> None:
    baseline_run_id = _insert_simulation_run(
        session, _insert_simulation(session, public_api_rows)
    )
    reform_run_id = _insert_simulation_run(
        session, _insert_simulation(session, public_api_rows)
    )

    with refused(session, match="baseline_simulation_run_id"):
        _insert_report_run(session, public_api_rows, None)
    with refused(session, match="foreign key constraint"):
        _insert_report_run(session, public_api_rows, uuid4())
    # A household report with only a baseline names no reform run.
    _insert_report_run(session, public_api_rows, baseline_run_id)
    report_run_id = _insert_report_run(
        session, public_api_rows, baseline_run_id, reform_run_id
    )
    for run_id in (baseline_run_id, reform_run_id):
        with refused(session, match="foreign key constraint"):
            session.execute(
                delete(SimulationRun).where(col(SimulationRun.id) == run_id)
            )
    session.execute(delete(ReportRun).where(col(ReportRun.id) == report_run_id))
    assert _count(session, col(SimulationRun.id), reform_run_id) == 1


def test_results_are_unique_per_run_and_name_runs_that_exist(
    session: Session, public_api_rows: PublicApiRows
) -> None:
    baseline_run_id = _insert_simulation_run(
        session, _insert_simulation(session, public_api_rows)
    )
    reform_run_id = _insert_simulation_run(
        session, _insert_simulation(session, public_api_rows)
    )
    comparison_runs = {
        "report_run_id": _insert_report_run(
            session, public_api_rows, baseline_run_id, reform_run_id
        ),
        "baseline_simulation_run_id": baseline_run_id,
        "reform_simulation_run_id": reform_run_id,
    }

    with refused(session):
        add_row(
            session,
            BudgetSummary,
            id=uuid4(),
            variable_name="household_net_income",
            entity="household",
            **{**comparison_runs, "reform_simulation_run_id": uuid4()},
        )
    poverty = {
        "simulation_run_id": reform_run_id,
        "poverty_type": "spm",
        "entity": "person",
    }
    add_row(session, Poverty, id=uuid4(), **poverty)
    with refused(session):
        add_row(session, Poverty, id=uuid4(), **poverty)
    for group in ("child", "adult"):
        add_row(
            session,
            Poverty,
            id=uuid4(),
            filter_variable="age",
            filter_group=group,
            **poverty,
        )
    decile = {
        "income_variable": "household_net_income",
        "entity": "household",
        "decile": 1,
        "quantiles": 10,
        **comparison_runs,
    }
    add_row(session, DecileImpact, id=uuid4(), **decile)
    add_row(
        session,
        DecileImpact,
        id=uuid4(),
        decile_variable="household_wealth_decile",
        **decile,
    )
    with refused(session):
        add_row(session, DecileImpact, id=uuid4(), **decile)
    budget = {"variable_name": "household_tax", "entity": "household"}
    add_row(session, BudgetSummary, id=uuid4(), **budget, **comparison_runs)
    # A report run compares one pair, so its rows are unique within it.
    with refused(session):
        add_row(
            session,
            BudgetSummary,
            id=uuid4(),
            **budget,
            **{**comparison_runs, "reform_simulation_run_id": baseline_run_id},
        )
    add_row(
        session,
        ProgramStatistics,
        id=uuid4(),
        program_name="income_tax",
        **comparison_runs,
    )
    with refused(session):
        add_row(
            session,
            ProgramStatistics,
            id=uuid4(),
            program_name="income_tax",
            **comparison_runs,
        )
    constituency = {
        "constituency_name": "Aldershot",
        "average_household_income_change": 1.0,
        "relative_household_income_change": 0.01,
        "population": 100.0,
        **comparison_runs,
    }
    add_row(
        session,
        ConstituencyImpact,
        id=uuid4(),
        constituency_code="E14000530",
        disclosure_tier="approximate",
        **constituency,
    )
    with refused(session):
        add_row(
            session,
            ConstituencyImpact,
            id=uuid4(),
            constituency_code="E14000531",
            disclosure_tier="withheld",
            **constituency,
        )


def test_a_report_runs_labor_supply_and_cliff_impact_are_typed(
    session: Session, public_api_rows: PublicApiRows
) -> None:
    report_run_id = _insert_report_run(
        session,
        public_api_rows,
        _insert_simulation_run(session, _insert_simulation(session, public_api_rows)),
        _insert_simulation_run(session, _insert_simulation(session, public_api_rows)),
    )
    response = dict.fromkeys(LABOR_SUPPLY_RESPONSE_COLUMNS, 1.0)

    add_row(
        session,
        LaborSupplyResponse,
        id=uuid4(),
        report_run_id=report_run_id,
        **response,
    )
    with refused(session):
        add_row(
            session,
            LaborSupplyResponse,
            id=uuid4(),
            report_run_id=report_run_id,
            **response,
        )
    # .py reports a relative response only for deciles above zero.
    add_row(
        session,
        LaborSupplyDecileResponse,
        id=uuid4(),
        report_run_id=report_run_id,
        decile=0,
        average_income_effect=-1.0,
        average_substitution_effect=2.0,
    )
    add_row(
        session,
        LaborSupplyDecileResponse,
        id=uuid4(),
        report_run_id=report_run_id,
        decile=1,
        average_income_effect=-1.0,
        average_substitution_effect=2.0,
        relative_income_effect=-0.01,
        relative_substitution_effect=0.02,
    )
    with refused(session):
        add_row(
            session,
            LaborSupplyDecileResponse,
            id=uuid4(),
            report_run_id=report_run_id,
            decile=1,
        )
    with refused(session, match="ck_report_runs_cliff_impact_complete"):
        _update_report_run(session, report_run_id, baseline_cliff_gap=1.0)
    _update_report_run(
        session,
        report_run_id,
        baseline_cliff_gap=1.0,
        baseline_cliff_share=0.1,
        reform_cliff_gap=2.0,
        reform_cliff_share=0.2,
        data_version="1.0.0",
        spm_provenance={"source": "census"},
    )
    receipt_type = session.scalars(
        select(func.jsonb_typeof(col(ReportRun.spm_provenance))).where(
            col(ReportRun.id) == report_run_id
        )
    ).one()
    assert receipt_type == "object"

    session.execute(delete(ReportRun).where(col(ReportRun.id) == report_run_id))
    for report_run_column in (
        col(LaborSupplyResponse.report_run_id),
        col(LaborSupplyDecileResponse.report_run_id),
    ):
        assert _count(session, report_run_column, report_run_id) == 0


def _insert_report(
    session: Session, public_api_rows: PublicApiRows, **values: object
) -> UUID:
    report_id = uuid4()
    add_row(
        session,
        Report,
        id=report_id,
        label="Budget window",
        country="us",
        tax_benefit_model_id=public_api_rows.model_id,
        inputs={},
        **values,
    )
    return report_id


def _insert_budget_window_run(
    session: Session, public_api_rows: PublicApiRows, report_id: UUID
) -> UUID:
    window_run_id = uuid4()
    add_row(
        session,
        BudgetWindowRun,
        id=window_run_id,
        report_id=report_id,
        tax_benefit_model_version_id=public_api_rows.version_id,
        trigger="initial",
        recalculate=False,
        status="running",
    )
    return window_run_id


def test_budget_windows_hold_one_report_run_per_year(
    session: Session, public_api_rows: PublicApiRows
) -> None:
    for refused_values in (
        {"year": 2026, "budget_window_size": 0},
        {"year": 2026, "budget_window_size": 76},
        {"year": 2190, "budget_window_size": 12},
        {"budget_window_size": 3},
        {"year": 2026, "budget_window_size": 3, "household_id": None},
    ):
        values: dict[str, object] = dict(refused_values)
        if "household_id" in values:
            values["household_id"] = public_api_rows.household_id
        with refused(session, match="ck_reports_budget_window_size"):
            _insert_report(session, public_api_rows, **values)
    report_id = _insert_report(
        session, public_api_rows, year=2026, budget_window_size=3
    )
    other_report_id = _insert_report(session, public_api_rows, year=2026)
    window_run_id = _insert_budget_window_run(session, public_api_rows, report_id)
    simulation_id = _insert_simulation(session, public_api_rows)

    def insert_year(year: int | None, *, of_report: UUID = report_id) -> None:
        add_row(
            session,
            ReportRun,
            id=uuid4(),
            report_id=of_report,
            budget_window_run_id=window_run_id,
            year=year,
            # Each year of a window has simulations of its own, as the
            # simulation service gives it.
            baseline_simulation_run_id=_insert_simulation_run(
                session,
                _insert_simulation(session, public_api_rows),
                year=year or 2026,
            ),
            status="pending",
            trigger="initial",
            **RUN_VERSIONS,
        )

    insert_year(2026)
    insert_year(2027)
    with refused(session, match="uq_report_runs_budget_window_run_id_year"):
        insert_year(2027)
    with refused(session, match="ck_report_runs_budget_window_year"):
        insert_year(None)
    with refused(session, match="foreign key constraint"):
        insert_year(2028, of_report=other_report_id)
    with refused(session, match="ck_simulation_runs_year"):
        _insert_simulation_run(session, simulation_id, year=1800)
    # A window run owns its years, as the report owns its runs.
    second_window_run_id = _insert_budget_window_run(
        session, public_api_rows, report_id
    )
    session.execute(
        delete(BudgetWindowRun).where(col(BudgetWindowRun.id) == window_run_id)
    )
    assert _count(session, col(ReportRun.budget_window_run_id), window_run_id) == 0

    session.execute(delete(Report).where(col(Report.id) == report_id))
    assert _count(session, col(BudgetWindowRun.id), second_window_run_id) == 0
    assert _count(session, col(ReportRun.report_id), report_id) == 0


def test_household_jobs_take_a_valid_year_and_record_when_they_end(
    session: Session, public_api_rows: PublicApiRows
) -> None:
    household_job = {
        "country": "us",
        "household_id": public_api_rows.household_id,
        "request_data": {},
        "tax_benefit_model_version_id": public_api_rows.version_id,
        **RUN_VERSIONS,
    }
    add_row(
        session,
        HouseholdJob,
        id=uuid4(),
        year=2026,
        status="pending",
        **household_job,
    )

    with refused(session):
        add_row(
            session,
            HouseholdJob,
            id=uuid4(),
            year=1800,
            status="pending",
            **household_job,
        )
    with refused(session):
        add_row(
            session,
            HouseholdJob,
            id=uuid4(),
            year=2026,
            status="failed",
            **household_job,
        )

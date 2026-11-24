"""Store reports, simulations and their runs' results for the read integration tests.

The simulation service and its Modal workers write these tables in staging
and production; here the disposable database's owner writes them through a
Session on the mapped classes, commits them so API v1's runtime role can read
them, and deletes them again. Results are stored through the port of the
simulation service's writer in ``tests.fixtures.economy_results``.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import delete, select, update
from sqlmodel import col

from policyengine_api.data.v2.models import (
    BudgetSummary,
    BudgetWindowRun,
    CongressionalDistrictImpact,
    ConstituencyImpact,
    Country,
    Dataset,
    DecileImpact,
    Household,
    Inequality,
    IntraDecileImpact,
    LaborSupplyDecileResponse,
    LaborSupplyResponse,
    LocalAuthorityImpact,
    Policy,
    Poverty,
    ProgramStatistics,
    Region,
    Report,
    ReportRun,
    Simulation,
    SimulationRun,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    WithheldAreaCode,
)
from tests.fixtures.economy_results import RunIds, economy_result_rows
from tests.integration.simulation_rows import add_row

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import Session, sessionmaker

REGION_CODES = {"us": "state/ca", "uk": "country/wales"}
DATASET_NAMES = {"us": "enhanced_cps_2024", "uk": "enhanced_frs_2023_24"}
# The dataset .py 6.17.1's UK bundle gives constituencies and local authorities.
LOCAL_AREA_DATASET_NAME = "microcosm_uk_2024_25_dense"
STARTED_AT = datetime(2026, 11, 1, 9, tzinfo=UTC)
# The year of a report store_report stores, unless it is given another.
STORED_REPORT_YEAR = 2026
# The mapped class of each table the simulation service's writer stores
# result rows in, by the table's name in ``economy_result_rows``.
RESULT_MODELS: dict[str, type[Any]] = {
    model.__tablename__: model
    for model in (
        LaborSupplyResponse,
        LaborSupplyDecileResponse,
        BudgetSummary,
        DecileImpact,
        IntraDecileImpact,
        Poverty,
        Inequality,
        ProgramStatistics,
        CongressionalDistrictImpact,
        ConstituencyImpact,
        LocalAuthorityImpact,
        WithheldAreaCode,
    )
}


@dataclass
class CatalogRows:
    """A country's model, a catalog version of it, a dataset, a region and a policy.

    ``created_model`` says whether the model row was stored here, so cleanup
    leaves a model another test stored. ``area_region_ids`` and
    ``area_dataset_ids`` are the UK-wide and area regions and the local-area
    dataset ``store_local_area_catalog`` adds.
    """

    country: str
    model_id: UUID
    version_id: UUID
    dataset_id: UUID
    region_id: UUID
    policy_id: UUID
    created_model: bool
    report_ids: list[UUID] = field(default_factory=list)
    simulation_ids: list[UUID] = field(default_factory=list)
    household_ids: list[UUID] = field(default_factory=list)
    area_region_ids: list[UUID] = field(default_factory=list)
    area_dataset_ids: list[UUID] = field(default_factory=list)


def store_catalog(session: Session, country: str) -> CatalogRows:
    """Store a catalog version, dataset, region and policy of the country's model."""
    model_name = f"policyengine-{country}"
    model_id = session.execute(
        select(col(TaxBenefitModel.id)).where(col(TaxBenefitModel.name) == model_name)
    ).scalar_one_or_none()
    created_model = model_id is None
    if model_id is None:
        model_id = uuid4()
        add_row(session, TaxBenefitModel, id=model_id, name=model_name)
    rows = CatalogRows(
        country=country,
        model_id=model_id,
        version_id=uuid4(),
        dataset_id=uuid4(),
        region_id=uuid4(),
        policy_id=uuid4(),
        created_model=created_model,
    )
    add_row(
        session,
        TaxBenefitModelVersion,
        id=rows.version_id,
        model_id=model_id,
        version=f"reads-{rows.version_id.hex[:12]}",
        current_law_id=1,
        metadata_time_periods=[2026],
    )
    add_row(
        session,
        Dataset,
        id=rows.dataset_id,
        name=DATASET_NAMES[country],
        year=2026,
        is_output_dataset=False,
        tax_benefit_model_version_id=rows.version_id,
    )
    add_row(
        session,
        Region,
        id=rows.region_id,
        code=REGION_CODES[country],
        label=REGION_CODES[country],
        region_type="state" if country == "us" else "country",
        requires_filter=False,
        tax_benefit_model_version_id=rows.version_id,
        default_dataset_id=rows.dataset_id,
    )
    add_row(
        session,
        Policy,
        id=rows.policy_id,
        country_id=country,
        tax_benefit_model_id=model_id,
        tax_benefit_model_version_id=rows.version_id,
        canonicalization_version=1,
        content_hash=uuid4().hex * 2,
    )
    return rows


def store_local_area_catalog(session: Session, catalog: CatalogRows) -> CatalogRows:
    """Give a UK catalog version its UK-wide region and local areas, as .py 6.17.1.

    UK-wide uses the catalog's national dataset; a constituency and a local
    authority use the local-area dataset, which this stores. Return the
    catalog with the UK-wide region and the local-area dataset in place of
    its own, for storing a local-area report; it records what it stores in
    ``catalog``'s lists, so ``delete_catalog(catalog)`` deletes it.
    """
    local_area_dataset_id = uuid4()
    add_row(
        session,
        Dataset,
        id=local_area_dataset_id,
        name=LOCAL_AREA_DATASET_NAME,
        year=2026,
        is_output_dataset=False,
        tax_benefit_model_version_id=catalog.version_id,
    )
    catalog.area_dataset_ids.append(local_area_dataset_id)
    regions = {
        "uk": ("national", catalog.dataset_id),
        "constituency/W07000081": ("constituency", local_area_dataset_id),
        "local_authority/W06000015": ("local_authority", local_area_dataset_id),
    }
    region_ids = {}
    for code, (region_type, dataset_id) in regions.items():
        region_ids[code] = uuid4()
        add_row(
            session,
            Region,
            id=region_ids[code],
            code=code,
            label=code,
            region_type=region_type,
            requires_filter=False,
            tax_benefit_model_version_id=catalog.version_id,
            default_dataset_id=dataset_id,
        )
        catalog.area_region_ids.append(region_ids[code])
    return replace(
        catalog, dataset_id=local_area_dataset_id, region_id=region_ids["uk"]
    )


def store_simulation(
    session: Session,
    catalog: CatalogRows,
    *,
    policy_id: UUID | None,
    year: int = STORED_REPORT_YEAR,
) -> UUID:
    """Store an economy simulation in ``year`` of the catalog's dataset and region."""
    simulation_id = uuid4()
    add_row(
        session,
        Simulation,
        id=simulation_id,
        simulation_type="economy",
        dataset_id=catalog.dataset_id,
        policy_id=policy_id,
        tax_benefit_model_version_id=catalog.version_id,
        region_id=catalog.region_id,
        year=year,
    )
    catalog.simulation_ids.append(simulation_id)
    return simulation_id


@dataclass(frozen=True)
class BudgetWindowYear:
    """A year of a budget-window run, which a report run of the report calculates."""

    budget_window_run_id: UUID
    year: int


@dataclass(frozen=True)
class RunSettings:
    """A run's package versions, status, creation time and failure message.

    ``run_id`` is the run's ID, a new one when None; a report run's
    simulation runs always get new ones. A report run with a
    ``budget_window_year`` is that year of that budget-window run, and its
    simulation runs are of that year. A ``forced`` report run, and its
    simulation runs, are a forced re-run's: extra runs beside the one unfailed
    run per version set.
    """

    versions: dict[str, str]
    status: str = "succeeded"
    created_at: datetime = STARTED_AT
    error_message: str | None = None
    run_id: UUID | None = None
    budget_window_year: BudgetWindowYear | None = None
    forced: bool = False

    @property
    def finished(self) -> bool:
        return self.status in {"succeeded", "failed"}


def store_simulation_run(
    session: Session,
    catalog: CatalogRows,
    simulation_id: UUID,
    settings: RunSettings,
    *,
    year: int = STORED_REPORT_YEAR,
) -> UUID:
    """Store one run of the simulation in ``year``.

    A finished run has a completion time.
    """
    run_id = uuid4() if settings.run_id is None else settings.run_id
    created_at = settings.created_at
    add_row(
        session,
        SimulationRun,
        id=run_id,
        created_at=created_at,
        simulation_id=simulation_id,
        year=year,
        tax_benefit_model_version_id=catalog.version_id,
        dataset_id=catalog.dataset_id,
        region_id=catalog.region_id,
        status=settings.status,
        started_at=created_at,
        completed_at=created_at + timedelta(minutes=5) if settings.finished else None,
        forced=settings.forced,
        **settings.versions,
    )
    return run_id


@dataclass(frozen=True)
class StoredReport:
    """A stored economy report and the simulations it compares."""

    report_id: UUID
    baseline_simulation_id: UUID
    reform_simulation_id: UUID
    year: int = STORED_REPORT_YEAR


def store_report(  # noqa: PLR0913  # the session and catalog, then each column a test varies
    session: Session,
    catalog: CatalogRows,
    *,
    household_id: UUID | None = None,
    budget_window_size: int | None = None,
    year: int = STORED_REPORT_YEAR,
    dataset_independent_key: str | None = None,
    created_at: datetime | None = None,
) -> StoredReport:
    """Store a report of ``year`` comparing current law with the catalog's policy.

    A budget window's ``year`` is its first year, whose simulations the
    report names. With ``dataset_independent_key``, the report has keys, as
    the simulation service stores them from C1 · 27 on: that key, and a
    definition key of its own; without it, it has none. Without
    ``created_at``, the report is created now.
    """
    report = StoredReport(
        report_id=uuid4(),
        baseline_simulation_id=store_simulation(
            session, catalog, policy_id=None, year=year
        ),
        reform_simulation_id=store_simulation(
            session, catalog, policy_id=catalog.policy_id, year=year
        ),
        year=year,
    )
    # Without a creation time, the report takes the model's: now.
    creation = {} if created_at is None else {"created_at": created_at}
    add_row(
        session,
        Report,
        id=report.report_id,
        label=f"{catalog.country} reform",
        description="A stored report",
        country=catalog.country,
        type="economy",
        tax_benefit_model_id=catalog.model_id,
        policy_id=catalog.policy_id,
        baseline_simulation_id=report.baseline_simulation_id,
        reform_simulation_id=report.reform_simulation_id,
        household_id=household_id,
        dataset_id=catalog.dataset_id,
        region_id=catalog.region_id,
        year=year,
        budget_window_size=budget_window_size,
        inputs={"include_cliffs": True},
        key_version=None if dataset_independent_key is None else 1,
        definition_key=None if dataset_independent_key is None else uuid4().hex * 2,
        dataset_independent_key=dataset_independent_key,
        **creation,
    )
    catalog.report_ids.append(report.report_id)
    return report


def store_report_run(
    session: Session,
    catalog: CatalogRows,
    report: StoredReport,
    settings: RunSettings,
    result: dict[str, Any] | None = None,
) -> RunIds:
    """Store a run of the report and its two simulation runs.

    With ``result``, the run's result columns and rows are stored as the
    simulation service's writer stores that economy result.
    """
    budget_window_year = settings.budget_window_year
    simulation_run_settings = replace(settings, run_id=None)
    simulation_year = (
        report.year if budget_window_year is None else budget_window_year.year
    )
    run_ids = RunIds(
        report_run_id=uuid4() if settings.run_id is None else settings.run_id,
        baseline_simulation_run_id=store_simulation_run(
            session,
            catalog,
            report.baseline_simulation_id,
            simulation_run_settings,
            year=simulation_year,
        ),
        reform_simulation_run_id=store_simulation_run(
            session,
            catalog,
            report.reform_simulation_id,
            simulation_run_settings,
            year=simulation_year,
        ),
    )
    stored = (
        None
        if result is None
        else economy_result_rows(result, run_ids=run_ids, country=catalog.country)
    )
    result_columns: dict[str, Any] = (
        {} if stored is None else dict(stored.report_run_columns)
    )
    created_at = settings.created_at
    add_row(
        session,
        ReportRun,
        id=run_ids.report_run_id,
        created_at=created_at,
        report_id=report.report_id,
        baseline_simulation_run_id=run_ids.baseline_simulation_run_id,
        reform_simulation_run_id=run_ids.reform_simulation_run_id,
        budget_window_run_id=(
            None
            if budget_window_year is None
            else budget_window_year.budget_window_run_id
        ),
        year=None if budget_window_year is None else budget_window_year.year,
        status=settings.status,
        trigger="initial",
        started_at=created_at,
        completed_at=created_at + timedelta(minutes=10) if settings.finished else None,
        error_message=settings.error_message,
        forced=settings.forced,
        **result_columns,
        **settings.versions,
    )
    if stored is not None:
        for table, rows in stored.rows.items():
            for row in rows:
                add_row(session, RESULT_MODELS[table], id=uuid4(), **row)
    return run_ids


def store_budget_window_run(
    session: Session,
    catalog: CatalogRows,
    report: StoredReport,
    settings: RunSettings,
) -> UUID:
    """Store a calculation of the budget-window report, without its years.

    Store each year with ``store_report_run``, whose settings name the year.
    """
    run_id = uuid4() if settings.run_id is None else settings.run_id
    created_at = settings.created_at
    add_row(
        session,
        BudgetWindowRun,
        id=run_id,
        created_at=created_at,
        report_id=report.report_id,
        tax_benefit_model_version_id=catalog.version_id,
        trigger="initial",
        recalculate=False,
        status=settings.status,
        error_message=settings.error_message,
        started_at=None if settings.status == "pending" else created_at,
        completed_at=created_at + timedelta(hours=1) if settings.finished else None,
    )
    return run_id


def _delete_rows(session: Session, model: type[Any], row_ids: list[UUID]) -> None:
    for row_id in row_ids:
        session.execute(delete(model).where(model.id == row_id))


def delete_catalog(session: Session, catalog: CatalogRows) -> None:
    """Delete the reports, simulations, households and catalog rows of ``catalog``.

    A report's runs and results go with it, and a simulation's runs with it.
    """
    _delete_rows(session, Report, catalog.report_ids)
    _delete_rows(session, Simulation, catalog.simulation_ids)
    _delete_rows(session, Household, catalog.household_ids)
    _delete_rows(session, Region, catalog.area_region_ids)
    _delete_rows(session, Dataset, catalog.area_dataset_ids)
    for model, row_id in (
        (Policy, catalog.policy_id),
        (Region, catalog.region_id),
        (Dataset, catalog.dataset_id),
        (TaxBenefitModelVersion, catalog.version_id),
    ):
        _delete_rows(session, model, [row_id])
    if catalog.created_model:
        _delete_rows(session, TaxBenefitModel, [catalog.model_id])


def _set_society_wide_enabled(session: Session, country: str, *, enabled: bool) -> None:
    session.execute(
        update(Country)
        .where(col(Country.id) == country)
        .values(society_wide_enabled=enabled)
    )


@contextmanager
def household_only_catalog(
    sessions: sessionmaker[Session], country: str
) -> Iterator[CatalogRows]:
    """Make the country household-only, store its catalog, and restore both after.

    The country keeps household calculations but loses economy reports.
    """
    with sessions.begin() as session:
        _set_society_wide_enabled(session, country, enabled=False)
        catalog = store_catalog(session, country)
    try:
        yield catalog
    finally:
        # Each in its own transaction, so a failed cleanup still restores the
        # country.
        with sessions.begin() as session:
            _set_society_wide_enabled(session, country, enabled=True)
        with sessions.begin() as session:
            delete_catalog(session, catalog)


def store_year_simulations(
    session: Session, catalog: CatalogRows, report: StoredReport, year: int
) -> StoredReport:
    """Return the report with the simulations a year of its budget window uses.

    As the simulation service creates a window, its first year (the report's
    ``year``) uses the report's two simulations. Each later year gets a
    baseline and a reform simulation of its own year, with the same
    policies, which this stores.
    """
    if year == report.year:
        return report
    return StoredReport(
        report_id=report.report_id,
        baseline_simulation_id=store_simulation(
            session, catalog, policy_id=None, year=year
        ),
        reform_simulation_id=store_simulation(
            session, catalog, policy_id=catalog.policy_id, year=year
        ),
        year=report.year,
    )

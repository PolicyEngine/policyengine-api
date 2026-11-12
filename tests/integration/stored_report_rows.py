"""Store reports, simulations and their runs' results for the read integration tests.

The simulation service and its Modal workers write these tables in staging
and production; here the disposable database's owner writes them, commits
them so the Public API's runtime role can read them, and deletes them again.
Results are stored through the port of the simulation service's writer in
``tests.fixtures.economy_results``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import bindparam

from tests.fixtures.economy_results import RunIds, economy_result_rows
from tests.integration.simulation_rows import insert_row

if TYPE_CHECKING:
    from sqlalchemy import Connection

REGION_CODES = {"us": "state/ca", "uk": "country/wales"}
DATASET_NAMES = {"us": "enhanced_cps_2024", "uk": "enhanced_frs_2023_24"}
STARTED_AT = datetime(2026, 11, 1, 9, tzinfo=UTC)
# The year of a report store_report stores, unless it is given another.
STORED_REPORT_YEAR = 2026


@dataclass
class CatalogRows:
    """A country's model, a catalog version of it, a dataset, a region and a policy.

    ``created_model`` says whether the model row was stored here, so cleanup
    leaves a model another test stored.
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


def store_catalog(connection: Connection, country: str) -> CatalogRows:
    """Store a catalog version, dataset, region and policy of the country's model."""
    model_name = f"policyengine-{country}"
    model_id = connection.execute(
        text("SELECT id FROM tax_benefit_models WHERE name = :name"),
        {"name": model_name},
    ).scalar_one_or_none()
    created_model = model_id is None
    if model_id is None:
        model_id = uuid4()
        insert_row(connection, "tax_benefit_models", id=model_id, name=model_name)
    rows = CatalogRows(
        country=country,
        model_id=model_id,
        version_id=uuid4(),
        dataset_id=uuid4(),
        region_id=uuid4(),
        policy_id=uuid4(),
        created_model=created_model,
    )
    insert_row(
        connection,
        "tax_benefit_model_versions",
        id=rows.version_id,
        model_id=model_id,
        version=f"reads-{rows.version_id.hex[:12]}",
        current_law_id=1,
        metadata_time_periods="[2026]",
    )
    insert_row(
        connection,
        "datasets",
        id=rows.dataset_id,
        name=DATASET_NAMES[country],
        year=2026,
        is_output_dataset=False,
        tax_benefit_model_version_id=rows.version_id,
    )
    insert_row(
        connection,
        "regions",
        id=rows.region_id,
        code=REGION_CODES[country],
        label=REGION_CODES[country],
        region_type="state" if country == "us" else "country",
        requires_filter=False,
        tax_benefit_model_version_id=rows.version_id,
        default_dataset_id=rows.dataset_id,
    )
    insert_row(
        connection,
        "policies",
        id=rows.policy_id,
        country_id=country,
        tax_benefit_model_id=model_id,
        tax_benefit_model_version_id=rows.version_id,
        canonicalization_version=1,
        content_hash=uuid4().hex * 2,
    )
    return rows


def store_simulation(
    connection: Connection,
    catalog: CatalogRows,
    *,
    policy_id: UUID | None,
    year: int = STORED_REPORT_YEAR,
) -> UUID:
    """Store an economy simulation in ``year`` of the catalog's dataset and region."""
    simulation_id = uuid4()
    insert_row(
        connection,
        "simulations",
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
    simulation runs are of that year.
    """

    versions: dict[str, str]
    status: str = "succeeded"
    created_at: datetime = STARTED_AT
    error_message: str | None = None
    run_id: UUID | None = None
    budget_window_year: BudgetWindowYear | None = None

    @property
    def finished(self) -> bool:
        return self.status in {"succeeded", "failed"}


def store_simulation_run(
    connection: Connection,
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
    insert_row(
        connection,
        "simulation_runs",
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


def store_report(
    connection: Connection,
    catalog: CatalogRows,
    *,
    household_id: UUID | None = None,
    budget_window_size: int | None = None,
    year: int = STORED_REPORT_YEAR,
) -> StoredReport:
    """Store a report of ``year`` comparing current law with the catalog's policy.

    A budget window's ``year`` is its first year, whose simulations the
    report names.
    """
    report = StoredReport(
        report_id=uuid4(),
        baseline_simulation_id=store_simulation(
            connection, catalog, policy_id=None, year=year
        ),
        reform_simulation_id=store_simulation(
            connection, catalog, policy_id=catalog.policy_id, year=year
        ),
        year=year,
    )
    connection.execute(
        text(
            "INSERT INTO reports (id, label, description, country, type, "
            "tax_benefit_model_id, policy_id, baseline_simulation_id, "
            "reform_simulation_id, household_id, dataset_id, region_id, year, "
            "budget_window_size, inputs) VALUES (:id, :label, :description, "
            ":country, :type, :model_id, :policy_id, :baseline, :reform, "
            ":household_id, :dataset_id, :region_id, :year, :budget_window_size, "
            "CAST(:inputs AS JSON))"
        ),
        {
            "id": report.report_id,
            "label": f"{catalog.country} reform",
            "description": "A stored report",
            "country": catalog.country,
            "type": "economy",
            "model_id": catalog.model_id,
            "policy_id": catalog.policy_id,
            "baseline": report.baseline_simulation_id,
            "reform": report.reform_simulation_id,
            "household_id": household_id,
            "dataset_id": catalog.dataset_id,
            "region_id": catalog.region_id,
            "budget_window_size": budget_window_size,
            "year": year,
            "inputs": '{"include_cliffs": true}',
        },
    )
    catalog.report_ids.append(report.report_id)
    return report


def store_report_run(
    connection: Connection,
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
            connection,
            catalog,
            report.baseline_simulation_id,
            simulation_run_settings,
            year=simulation_year,
        ),
        reform_simulation_run_id=store_simulation_run(
            connection,
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
    spm_provenance = result_columns.pop("spm_provenance", None)
    created_at = settings.created_at
    connection.execute(
        text(
            "INSERT INTO report_runs (id, created_at, report_id, "
            "baseline_simulation_run_id, reform_simulation_run_id, "
            "budget_window_run_id, year, "
            "country_package_version, policyengine_version, status, trigger, "
            "started_at, completed_at, error_message, spm_provenance"
            + "".join(f", {column}" for column in result_columns)
            + ") VALUES (:id, :created_at, :report_id, :baseline_run, "
            ":reform_run, :budget_window_run_id, :year, "
            ":country_package_version, :policyengine_version, "
            ":status, 'initial', :started_at, :completed_at, :error_message, "
            ":spm_provenance"
            + "".join(f", :{column}" for column in result_columns)
            + ")"
        ).bindparams(bindparam("spm_provenance", type_=JSONB)),
        {
            "id": run_ids.report_run_id,
            "created_at": created_at,
            "report_id": report.report_id,
            "baseline_run": run_ids.baseline_simulation_run_id,
            "reform_run": run_ids.reform_simulation_run_id,
            "budget_window_run_id": (
                None
                if budget_window_year is None
                else budget_window_year.budget_window_run_id
            ),
            "year": None if budget_window_year is None else budget_window_year.year,
            "status": settings.status,
            "started_at": created_at,
            "completed_at": (
                created_at + timedelta(minutes=10) if settings.finished else None
            ),
            "error_message": settings.error_message,
            "spm_provenance": spm_provenance,
            **settings.versions,
            **result_columns,
        },
    )
    if stored is not None:
        for table, rows in stored.rows.items():
            for row in rows:
                insert_row(connection, table, id=uuid4(), **row)
    return run_ids


def store_budget_window_run(
    connection: Connection,
    catalog: CatalogRows,
    report: StoredReport,
    settings: RunSettings,
) -> UUID:
    """Store a calculation of the budget-window report, without its years.

    Store each year with ``store_report_run``, whose settings name the year.
    """
    run_id = uuid4() if settings.run_id is None else settings.run_id
    created_at = settings.created_at
    insert_row(
        connection,
        "budget_window_runs",
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


def delete_catalog(connection: Connection, catalog: CatalogRows) -> None:
    """Delete the reports, simulations, households and catalog rows of ``catalog``.

    A report's runs and results go with it, and a simulation's runs with it.
    """
    for report_id in catalog.report_ids:
        connection.execute(
            text("DELETE FROM reports WHERE id = :id"), {"id": report_id}
        )
    for simulation_id in catalog.simulation_ids:
        connection.execute(
            text("DELETE FROM simulations WHERE id = :id"), {"id": simulation_id}
        )
    for household_id in catalog.household_ids:
        connection.execute(
            text("DELETE FROM households WHERE id = :id"), {"id": household_id}
        )
    for table, row_id in (
        ("policies", catalog.policy_id),
        ("regions", catalog.region_id),
        ("datasets", catalog.dataset_id),
        ("tax_benefit_model_versions", catalog.version_id),
    ):
        connection.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": row_id})
    if catalog.created_model:
        connection.execute(
            text("DELETE FROM tax_benefit_models WHERE id = :id"),
            {"id": catalog.model_id},
        )


def store_year_simulations(
    connection: Connection, catalog: CatalogRows, report: StoredReport, year: int
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
            connection, catalog, policy_id=None, year=year
        ),
        reform_simulation_id=store_simulation(
            connection, catalog, policy_id=catalog.policy_id, year=year
        ),
        year=report.year,
    )

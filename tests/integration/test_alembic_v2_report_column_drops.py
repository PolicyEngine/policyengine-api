"""Check the report column drops revision against disposable Postgres.

Revision 4e30076d4b9f, on the cliff impacts revision bc334f9877b7, drops what
shared report rows no longer hold: ``reports.label``, ``description`` and
``user_id``, ``report_runs.trigger`` and its four cliff columns, and
``budget_window_runs.trigger``, with the foreign key, index and check that
depend on them. The ``v2_report_run_trigger`` type stays, because
``user_report_run_associations`` uses it. The downgrade adds the columns back
without their values.
"""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
from alembic import command
from sqlalchemy import JSON, delete, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql.base import PGInspector
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlmodel import col

from policyengine_api.data.v2.migration_target import V2_ALEMBIC_DISPOSABLE_TEST
from policyengine_api.data.v2.models import (
    BudgetWindowRun,
    Report,
    ReportRun,
    Simulation,
    SimulationRun,
    User,
)
from policyengine_api.data.v2.privilege_reconciliation import (
    DEPLOYMENT_ENVIRONMENT,
    run,
)
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from tests.fixtures.database_sessions import grant, schema_inspector
from tests.fixtures.integration.alembic_v2 import alembic_v2_config
from tests.integration.simulation_rows import (
    RUN_VERSIONS,
    PublicApiRows,
    add_row,
    delete_public_api_rows,
    insert_public_api_rows,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.orm import sessionmaker
    from sqlmodel import Session

    from tests.integration.conftest import ManagedV2Roles

CLIFF_IMPACTS_REVISION = "bc334f9877b7"
REPORT_COLUMN_DROPS_REVISION = "4e30076d4b9f"
DROPPED_COLUMNS = {
    "reports": {"label", "description", "user_id"},
    "report_runs": {
        "trigger",
        "baseline_cliff_gap",
        "baseline_cliff_share",
        "reform_cliff_gap",
        "reform_cliff_share",
    },
    "budget_window_runs": {"trigger"},
}


def _existing_enum(type_name: str) -> postgresql.ENUM:
    """Return a column type naming an enum type the revisions already created.

    Rows name its values as text, which PostgreSQL checks against the type.
    """
    return postgresql.ENUM(name=type_name, create_type=False)


class ParentRevisionBase(DeclarativeBase):
    """The declarative base of the tables as the parent revision left them."""


class ReportAtParent(ParentRevisionBase):
    """A report's required columns, with the per-user ones the revision drops."""

    __tablename__ = "reports"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    label: Mapped[str | None]
    description: Mapped[str | None]
    user_id: Mapped[UUID | None]
    country: Mapped[str]
    tax_benefit_model_id: Mapped[UUID]
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON)


class ReportRunAtParent(ParentRevisionBase):
    """A report run's required columns, with its trigger and four cliff columns."""

    __tablename__ = "report_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    report_id: Mapped[UUID]
    baseline_simulation_run_id: Mapped[UUID]
    country_package_version: Mapped[str]
    policyengine_version: Mapped[str]
    status: Mapped[str] = mapped_column(_existing_enum("v2_report_run_status"))
    trigger: Mapped[str | None] = mapped_column(_existing_enum("v2_report_run_trigger"))
    baseline_cliff_gap: Mapped[float | None]
    baseline_cliff_share: Mapped[float | None]
    reform_cliff_gap: Mapped[float | None]
    reform_cliff_share: Mapped[float | None]


class BudgetWindowRunAtParent(ParentRevisionBase):
    """A budget-window run's required columns, with its trigger."""

    __tablename__ = "budget_window_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    report_id: Mapped[UUID]
    tax_benefit_model_version_id: Mapped[UUID]
    trigger: Mapped[str | None] = mapped_column(_existing_enum("v2_report_run_trigger"))
    recalculate: Mapped[bool]
    status: Mapped[str] = mapped_column(_existing_enum("v2_report_run_status"))


def _schema_shape(sessions: sessionmaker[Session]) -> dict[str, dict[str, Any]]:
    """Reflect every table's columns, keys, indexes and checks, by name."""
    inspector = schema_inspector(sessions)
    return {
        table_name: {
            "columns": {
                column["name"]: (
                    column["type"].compile(dialect=postgresql.dialect()),
                    column["nullable"],
                    column.get("default"),
                )
                for column in inspector.get_columns(table_name)
            },
            "primary_key": inspector.get_pk_constraint(table_name),
            "foreign_keys": {
                key["name"]: (
                    tuple(key["constrained_columns"]),
                    key["referred_table"],
                    key["options"].get("ondelete"),
                )
                for key in inspector.get_foreign_keys(table_name)
            },
            "unique_constraints": {
                unique["name"]: tuple(unique["column_names"])
                for unique in inspector.get_unique_constraints(table_name)
            },
            "indexes": {
                index["name"]: (
                    tuple(index["column_names"]),
                    index["unique"],
                    index.get("dialect_options", {}).get("postgresql_where"),
                )
                for index in inspector.get_indexes(table_name)
            },
            "checks": {
                check["name"]: check["sqltext"]
                for check in inspector.get_check_constraints(table_name)
            },
        }
        for table_name in inspector.get_table_names(schema="public")
        if table_name != "alembic_version"
    }


def _enum_labels(sessions: sessionmaker[Session]) -> dict[str, list[str]]:
    """Return each enum type in the public schema with its labels in order."""
    inspector = schema_inspector(sessions)
    assert isinstance(inspector, PGInspector)
    return {
        enum_type["name"]: enum_type["labels"]
        for enum_type in inspector.get_enums(schema="public")
    }


def _without_dropped_schema(
    parent_shape: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Return the parent's schema less what the revision should remove."""
    expected = deepcopy(parent_shape)
    for table_name, column_names in DROPPED_COLUMNS.items():
        for column_name in column_names:
            del expected[table_name]["columns"][column_name]
    del expected["reports"]["foreign_keys"]["fk_reports_user_id_users"]
    del expected["reports"]["indexes"]["ix_reports_user_id"]
    del expected["report_runs"]["checks"]["ck_report_runs_cliff_impact_complete"]
    return expected


def _privilege_environment(
    database_url: str, managed_v2_roles: ManagedV2Roles
) -> dict[str, str]:
    """Return what the deploy's privilege steps read."""
    return {
        V2_MIGRATION_DATABASE_URL: database_url,
        V2_ALEMBIC_DISPOSABLE_TEST: "1",
        DEPLOYMENT_ENVIRONMENT: managed_v2_roles.deployment_environment,
    }


@pytest.fixture
def sessions(
    v2_owner_sessions: sessionmaker[Session],
    disposable_v2_database_url: str,
    managed_v2_roles: ManagedV2Roles,
) -> Iterator[sessionmaker[Session]]:
    """Yield the owner's Session factories; leave the database at the v2 head.

    Downgrading to the base removes every table and its grants, so the roles
    get theirs back for the tests that run after this one.
    """
    try:
        yield v2_owner_sessions
    finally:
        command.upgrade(alembic_v2_config(), "head")
        apply_status = run(
            "apply",
            environ=_privilege_environment(
                disposable_v2_database_url, managed_v2_roles
            ),
        )
    assert apply_status == 0


def _build_parent_schema(sessions: sessionmaker[Session]) -> dict[str, dict[str, Any]]:
    """Build the parent revision from the base, without this revision's downgrade."""
    config = alembic_v2_config()
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, CLIFF_IMPACTS_REVISION)
    return _schema_shape(sessions)


def test_the_revision_drops_only_the_per_user_and_cliff_schema(
    sessions: sessionmaker[Session],
) -> None:
    parent_shape = _build_parent_schema(sessions)
    parent_enums = _enum_labels(sessions)

    command.upgrade(alembic_v2_config(), REPORT_COLUMN_DROPS_REVISION)

    assert _schema_shape(sessions) == _without_dropped_schema(parent_shape)
    assert _enum_labels(sessions) == parent_enums


def test_the_trigger_type_stays_for_each_users_run_records(
    sessions: sessionmaker[Session],
) -> None:
    command.upgrade(alembic_v2_config(), REPORT_COLUMN_DROPS_REVISION)

    assert _enum_labels(sessions)["v2_report_run_trigger"] == [
        "initial",
        "manual",
        "system",
    ]
    record_columns = _schema_shape(sessions)["user_report_run_associations"]["columns"]
    assert record_columns["trigger"][0] == "v2_report_run_trigger"


def _store_rows_with_dropped_values(
    session: Session, rows: PublicApiRows
) -> dict[str, UUID]:
    """Store a report, its run and its window run, each holding dropped values."""
    ids = {
        name: uuid4()
        for name in ("user", "simulation", "run", "report", "report_run", "window_run")
    }
    add_row(session, User, id=ids["user"], user_type="standard", primary_country="us")
    add_row(
        session,
        Simulation,
        id=ids["simulation"],
        simulation_type="economy",
        dataset_id=rows.dataset_id,
        tax_benefit_model_version_id=rows.version_id,
        year=2026,
    )
    add_row(
        session,
        SimulationRun,
        id=ids["run"],
        simulation_id=ids["simulation"],
        tax_benefit_model_version_id=rows.version_id,
        year=2026,
        status="pending",
        **RUN_VERSIONS,
    )
    add_row(
        session,
        ReportAtParent,
        id=ids["report"],
        label="Stored label",
        description="Stored description",
        user_id=ids["user"],
        country="us",
        tax_benefit_model_id=rows.model_id,
        inputs={},
    )
    add_row(
        session,
        ReportRunAtParent,
        id=ids["report_run"],
        report_id=ids["report"],
        baseline_simulation_run_id=ids["run"],
        status="pending",
        trigger="initial",
        baseline_cliff_gap=1.0,
        baseline_cliff_share=0.1,
        reform_cliff_gap=2.0,
        reform_cliff_share=0.2,
        **RUN_VERSIONS,
    )
    add_row(
        session,
        BudgetWindowRunAtParent,
        id=ids["window_run"],
        report_id=ids["report"],
        tax_benefit_model_version_id=rows.version_id,
        trigger="manual",
        recalculate=False,
        status="pending",
    )
    return ids


def _delete_stored_rows(session: Session, ids: dict[str, UUID]) -> None:
    """Delete the rows; deleting the report deletes its runs."""
    session.execute(delete(Report).where(col(Report.id) == ids["report"]))
    session.execute(delete(SimulationRun).where(col(SimulationRun.id) == ids["run"]))
    session.execute(delete(Simulation).where(col(Simulation.id) == ids["simulation"]))
    session.execute(delete(User).where(col(User.id) == ids["user"]))


def test_rows_survive_the_drop_and_a_downgrade_restores_columns_without_values(
    sessions: sessionmaker[Session],
) -> None:
    """The columns come back empty: a downgrade can't restore what was dropped."""
    config = alembic_v2_config()
    parent_shape = _build_parent_schema(sessions)
    with sessions.begin() as session:
        public_api_rows = insert_public_api_rows(session)
        ids = _store_rows_with_dropped_values(session, public_api_rows)
    try:
        command.upgrade(config, REPORT_COLUMN_DROPS_REVISION)

        with sessions() as session:
            kept_rows = session.execute(
                select(
                    col(Report.country),
                    col(ReportRun.status),
                    col(BudgetWindowRun.status),
                )
                .select_from(Report)
                .join(ReportRun, col(ReportRun.report_id) == col(Report.id))
                .join(BudgetWindowRun, col(BudgetWindowRun.report_id) == col(Report.id))
                .where(col(Report.id) == ids["report"])
            ).one()
        assert tuple(kept_rows) == ("us", "pending", "pending")

        command.downgrade(config, CLIFF_IMPACTS_REVISION)

        assert _schema_shape(sessions) == parent_shape
        with sessions() as session:
            restored_values = session.execute(
                select(
                    ReportAtParent.label,
                    ReportAtParent.description,
                    ReportAtParent.user_id,
                    ReportRunAtParent.trigger,
                    ReportRunAtParent.baseline_cliff_gap,
                    ReportRunAtParent.baseline_cliff_share,
                    ReportRunAtParent.reform_cliff_gap,
                    ReportRunAtParent.reform_cliff_share,
                    BudgetWindowRunAtParent.trigger,
                )
                .select_from(ReportAtParent)
                .join(
                    ReportRunAtParent,
                    ReportRunAtParent.report_id == ReportAtParent.id,
                )
                .join(
                    BudgetWindowRunAtParent,
                    BudgetWindowRunAtParent.report_id == ReportAtParent.id,
                )
                .where(ReportAtParent.id == ids["report"])
            ).one()
        assert set(restored_values) == {None}
    finally:
        with sessions.begin() as session:
            _delete_stored_rows(session, ids)
            delete_public_api_rows(session, public_api_rows)


def test_the_deploys_privilege_steps_pass_after_the_upgrade(
    sessions: sessionmaker[Session],
    disposable_v2_database_url: str,
    managed_v2_roles: ManagedV2Roles,
) -> None:
    """``apply`` and ``verify`` pass when the Modal worker held the cliff grants."""
    config = alembic_v2_config()
    command.upgrade(config, "head")
    command.downgrade(config, CLIFF_IMPACTS_REVISION)
    cliff_columns = ", ".join(sorted(DROPPED_COLUMNS["report_runs"] - {"trigger"}))
    with sessions.begin() as session:
        grant(
            session,
            f"UPDATE ({cliff_columns})",
            on=ReportRunAtParent,
            to=managed_v2_roles.modal_worker,
        )

    # The deploy upgrades to the head, which can be later than this revision,
    # before it applies the declared privileges, which name the head's tables.
    command.upgrade(config, "head")
    environ = _privilege_environment(disposable_v2_database_url, managed_v2_roles)

    assert run("apply", environ=environ) == 0
    assert run("verify", environ=environ) == 0

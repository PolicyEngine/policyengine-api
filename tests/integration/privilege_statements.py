"""Statements the v2 privilege tests send, built to name exactly their columns.

An ORM ``update`` of a v2 model also sets ``updated_at`` (its ``onupdate``),
and an ORM ``insert`` also writes the model's Python-side defaults, such as
``created_at``. A role that may not write those columns is refused because of
them, whatever it may do with the column a test names. A refusal sent through
a model therefore proves the role is refused the named column only where the
role may write ``updated_at`` and the defaults.

The classes here map only the columns the refusal tests name, on a registry
of their own, with no ``onupdate`` and no defaults. A statement through one
of them sends exactly the columns it names, so a refusal fails only for those
columns. Each class maps one table, with the columns of every test that
refuses a statement on it; a statement sends only the columns it sets. No
code creates tables from these classes: Alembic creates them from the models.

``ReportColumns`` also maps ``label``, ``ReportRunColumns`` ``trigger`` and the
four older cliff columns, and ``BudgetWindowRunColumns`` its ``trigger``: the
models' mappers leave them out until a revision drops them. No model maps
them, so every test that reads or writes them, or is refused them, sends its
statement through these classes.
"""

# No ``from __future__ import annotations``: SQLAlchemy reads the classes'
# ``Mapped`` annotations when it maps them, so their names stay imported at
# runtime.
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Update, bindparam, update
from sqlalchemy.orm import Mapped, class_mapper, mapped_column, registry
from sqlalchemy.types import TypeEngine
from sqlmodel import SQLModel

from policyengine_api.data.v2.models import (
    BudgetWindowRun,
    CliffImpact,
    ReportRun,
    ReportRunTrigger,
    Simulation,
    WithheldAreaCode,
)
from policyengine_api.data.v2.models.base import enum_type


def _type_of(model: type[SQLModel], column_name: str) -> TypeEngine[Any]:
    """Return a copy of the type the model gives a column, such as its enum type."""
    column_type: TypeEngine[Any] = class_mapper(model).columns[column_name].type
    return column_type.copy()


def _trigger_type() -> TypeEngine[Any]:
    """Return the runs' ``trigger`` type, which no model's mapper holds any more."""
    return enum_type(ReportRunTrigger, "v2_report_run_trigger")


named_column_tables = registry()


@named_column_tables.mapped
class SimulationColumns:
    """A simulation's key, and the columns of a new economy simulation."""

    __tablename__ = "simulations"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    definition_key: Mapped[str | None]
    simulation_type: Mapped[str] = mapped_column(
        _type_of(Simulation, "simulation_type")
    )
    dataset_id: Mapped[UUID | None]
    tax_benefit_model_version_id: Mapped[UUID]


@named_column_tables.mapped
class ReportColumns:
    """A report's key version, and its label, which its mapper leaves out."""

    __tablename__ = "reports"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    key_version: Mapped[int | None]
    label: Mapped[str | None]


@named_column_tables.mapped
class PolicyColumns:
    """A policy's content hash."""

    __tablename__ = "policies"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    content_hash: Mapped[str]


@named_column_tables.mapped
class HouseholdColumns:
    """A household's content hash."""

    __tablename__ = "households"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    content_hash: Mapped[str]


@named_column_tables.mapped
class CliffImpactColumns:
    """A new cliff calculation's columns, and its cliff gap."""

    __tablename__ = "cliff_impacts"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    simulation_run_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(_type_of(CliffImpact, "status"))
    cliff_gap: Mapped[float | None]


@named_column_tables.mapped
class PovertyColumns:
    """A new poverty result's columns, without its values."""

    __tablename__ = "poverty"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    simulation_run_id: Mapped[UUID]
    poverty_type: Mapped[str]
    entity: Mapped[str]


@named_column_tables.mapped
class LaborSupplyDecileResponseColumns:
    """A new labour supply decile result's columns, without its values."""

    __tablename__ = "labor_supply_decile_responses"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    report_run_id: Mapped[UUID]
    decile: Mapped[int]


@named_column_tables.mapped
class BudgetWindowRunColumns:
    """A new budget-window run's columns, and ``trigger``, which its mapper omits."""

    __tablename__ = "budget_window_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    report_id: Mapped[UUID]
    tax_benefit_model_version_id: Mapped[UUID]
    trigger: Mapped[str | None] = mapped_column(_trigger_type())
    recalculate: Mapped[bool]
    status: Mapped[str] = mapped_column(_type_of(BudgetWindowRun, "status"))


@named_column_tables.mapped
class ReportRunColumns:
    """A new report run's columns, ``trigger`` and the four older cliff columns.

    ``ReportRun``'s mapper leaves ``trigger`` and the cliff columns out until a
    revision drops them, so statements that set them go through this class.
    """

    __tablename__ = "report_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    report_id: Mapped[UUID]
    baseline_simulation_run_id: Mapped[UUID]
    country_package_version: Mapped[str]
    policyengine_version: Mapped[str]
    status: Mapped[str] = mapped_column(_type_of(ReportRun, "status"))
    trigger: Mapped[str | None] = mapped_column(_trigger_type())
    baseline_cliff_gap: Mapped[float | None]
    baseline_cliff_share: Mapped[float | None]
    reform_cliff_gap: Mapped[float | None]
    reform_cliff_share: Mapped[float | None]


# The four older cliff columns ``ReportRun``'s mapper leaves out, which only
# ``ReportRunColumns`` maps.
REPORT_RUN_CLIFF_COLUMNS = (
    "baseline_cliff_gap",
    "baseline_cliff_share",
    "reform_cliff_gap",
    "reform_cliff_share",
)


@named_column_tables.mapped
class WithheldAreaCodeColumns:
    """A new withheld area code's columns."""

    __tablename__ = "withheld_area_codes"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    report_run_id: Mapped[UUID]
    baseline_simulation_run_id: Mapped[UUID]
    reform_simulation_run_id: Mapped[UUID]
    area_type: Mapped[str] = mapped_column(_type_of(WithheldAreaCode, "area_type"))
    code: Mapped[str]


def update_row(model: type[Any], row_id: object, **values: object) -> Update:
    """Build an UPDATE of the model's row with ID ``row_id``, setting ``values``."""
    return update(model).where(model.id == row_id).values(**values)


def unfailed(status: Any, failed_status: str) -> ColumnElement[bool]:
    """Return ``status <> 'failed'``, with the failed status written as a literal.

    PostgreSQL matches an ``ON CONFLICT`` condition to a partial unique index's
    condition when it plans the statement. Once psycopg prepares a statement,
    after five runs on one connection, PostgreSQL plans it without its
    parameters' values, so a status sent as a parameter matches no index and
    the INSERT fails.
    """
    condition: ColumnElement[bool] = status != bindparam(
        "failed_status", failed_status, literal_execute=True
    )
    return condition

"""Exercise the v2 catalog tables' revisions against disposable Postgres.

Every statement runs through a Session (rule api.data.orm-only). Rows read or
written at head use the v2 models. Rows written at an earlier revision use the
small mapped classes below, which map the catalog columns a version stored
before catalog format 2 has; every revision these tests visit keeps them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from alembic import command
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlmodel import col

from policyengine_api.data.v2.models import (
    Parameter,
    ParameterSearchFile,
    ParameterTreeChild,
    TaxBenefitModelVersion,
    Variable,
)
from tests.fixtures.database_sessions import schema_inspector
from tests.fixtures.integration.alembic_v2 import alembic_v2_config, table_columns
from tests.integration.simulation_rows import add_row, refused

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

CATALOG_FORMAT_2_PARENT_REVISION = "fb1a3e40d3d6"
CATALOG_FORMAT_2_COLUMNS = {
    "tax_benefit_model_versions": ("catalog_format", "entities", "basic_inputs"),
    "variables": (
        "is_input_variable",
        "hidden_input",
        "module_name",
        "adds_parameter_path",
        "subtracts_parameter_path",
        "enum_values",
        "unit",
        "definition_period",
    ),
    "parameters": ("economy", "household"),
}
# The v2 model of each table with format 2 columns.
CATALOG_FORMAT_2_MODELS: dict[str, Any] = {
    "tax_benefit_model_versions": TaxBenefitModelVersion,
    "variables": Variable,
    "parameters": Parameter,
}
PROBE_MODEL_NAME = "catalog-format-probe"


class CatalogBeforeFormat2Base(DeclarativeBase):
    """The declarative base of the catalog tables before catalog format 2."""


class TaxBenefitModelBeforeCatalogFormat2(CatalogBeforeFormat2Base):
    """A tax-benefit model's name before catalog format 2."""

    __tablename__ = "tax_benefit_models"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str]


class TaxBenefitModelVersionBeforeCatalogFormat2(CatalogBeforeFormat2Base):
    """A model version's required columns before catalog format 2."""

    __tablename__ = "tax_benefit_model_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    model_id: Mapped[UUID]
    version: Mapped[str]
    current_law_id: Mapped[int]
    metadata_time_periods: Mapped[list[int]] = mapped_column(sa.JSON)


class VariableBeforeCatalogFormat2(CatalogBeforeFormat2Base):
    """A variable's required columns before catalog format 2."""

    __tablename__ = "variables"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str]
    entity: Mapped[str]
    default_value: Mapped[Any] = mapped_column(sa.JSON)
    tax_benefit_model_version_id: Mapped[UUID]


class ParameterBeforeCatalogFormat2(CatalogBeforeFormat2Base):
    """A parameter's required columns before catalog format 2."""

    __tablename__ = "parameters"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str]
    tax_benefit_model_version_id: Mapped[UUID]


def _catalog_version_published_before_format_2(session: Session) -> UUID:
    """Store a model version with one variable and one parameter; return its id."""
    model_id = uuid4()
    version_id = uuid4()
    add_row(
        session,
        TaxBenefitModelBeforeCatalogFormat2,
        id=model_id,
        name=PROBE_MODEL_NAME,
    )
    add_row(
        session,
        TaxBenefitModelVersionBeforeCatalogFormat2,
        id=version_id,
        model_id=model_id,
        version="0.0.1-probe",
        current_law_id=1,
        metadata_time_periods=[2026],
    )
    add_row(
        session,
        VariableBeforeCatalogFormat2,
        id=uuid4(),
        name="probe_income",
        entity="person",
        default_value=0,
        tax_benefit_model_version_id=version_id,
    )
    add_row(
        session,
        ParameterBeforeCatalogFormat2,
        id=uuid4(),
        name="gov.probe.rate",
        tax_benefit_model_version_id=version_id,
    )
    return version_id


def _delete_probe_catalog(sessions: sessionmaker[Session]) -> None:
    """Delete the probe model, and with it its versions and their catalog rows."""
    with sessions.begin() as session:
        session.execute(
            delete(TaxBenefitModelBeforeCatalogFormat2).where(
                TaxBenefitModelBeforeCatalogFormat2.name == PROBE_MODEL_NAME
            )
        )


def _version_row_count(model: Any, version_id: UUID) -> sa.Select[tuple[int]]:
    """Select how many of a catalog table's rows belong to the version."""
    return (
        select(func.count())
        .select_from(model)
        .where(model.tax_benefit_model_version_id == version_id)
    )


def _format_2_values(session: Session, version_id: UUID) -> list[tuple[Any, ...]]:
    """Return the format 2 columns of the version's model, variable and parameter."""
    rows = []
    for table_name, columns in CATALOG_FORMAT_2_COLUMNS.items():
        model = CATALOG_FORMAT_2_MODELS[table_name]
        key = (
            model.id
            if table_name == "tax_benefit_model_versions"
            else model.tax_benefit_model_version_id
        )
        format_2_columns = select(
            *(getattr(model, column_name) for column_name in columns)
        ).where(key == version_id)
        rows.append(tuple(session.execute(format_2_columns).one()))
    return rows


def test_catalog_format_2_columns_leave_earlier_versions_empty(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    """A version stored before catalog format 2 keeps its format 2 fields null.

    Upgrading adds the columns as nullable without writing to stored rows, and
    downgrading drops them and keeps every row.
    """
    config = alembic_v2_config()
    try:
        command.downgrade(config, CATALOG_FORMAT_2_PARENT_REVISION)
        for table_name, columns in CATALOG_FORMAT_2_COLUMNS.items():
            assert set(columns).isdisjoint(table_columns(v2_owner_sessions, table_name))
        with v2_owner_sessions.begin() as session:
            version_id = _catalog_version_published_before_format_2(session)

        command.upgrade(config, "head")

        for table_name, columns in CATALOG_FORMAT_2_COLUMNS.items():
            stored_columns = table_columns(v2_owner_sessions, table_name)
            for column_name in columns:
                assert stored_columns[column_name]["nullable"]
                assert stored_columns[column_name]["default"] is None
        with v2_owner_sessions() as session:
            assert _format_2_values(session, version_id) == [
                (None, None, None),
                (None, None, None, None, None, None, None, None),
                (None, None),
            ]

        command.downgrade(config, CATALOG_FORMAT_2_PARENT_REVISION)

        for table_name, columns in CATALOG_FORMAT_2_COLUMNS.items():
            assert set(columns).isdisjoint(table_columns(v2_owner_sessions, table_name))
        with v2_owner_sessions() as session:
            counts = session.execute(
                select(
                    _version_row_count(
                        VariableBeforeCatalogFormat2, version_id
                    ).scalar_subquery(),
                    _version_row_count(
                        ParameterBeforeCatalogFormat2, version_id
                    ).scalar_subquery(),
                )
            ).one()
        assert tuple(counts) == (1, 1)
    finally:
        _delete_probe_catalog(v2_owner_sessions)
        command.upgrade(config, "head")


PARAMETER_TREE_PARENT_REVISION = "e86f19a6c4da"


def test_parameter_tree_table_is_created_empty_and_dropped_without_data_loss(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    """The parameter tree revision creates an empty table and downgrades cleanly.

    The revision writes no rows: catalog publication writes each version's
    tree. A tree row is deleted with its version or its parameter, and
    downgrading drops the table while every catalog row stays.
    """
    config = alembic_v2_config()
    try:
        command.downgrade(config, PARAMETER_TREE_PARENT_REVISION)
        assert (
            "parameter_tree_children"
            not in schema_inspector(v2_owner_sessions).get_table_names()
        )
        with v2_owner_sessions.begin() as session:
            version_id = _catalog_version_published_before_format_2(session)

        command.upgrade(config, "head")

        indexes = {
            index["name"]: (index["column_names"], index["unique"])
            for index in schema_inspector(v2_owner_sessions).get_indexes(
                "parameter_tree_children"
            )
        }
        assert indexes["ix_parameter_tree_children_listing"] == (
            ["tax_benefit_model_version_id", "parent_path", "position"],
            True,
        )
        assert indexes["ix_parameter_tree_children_reform_listing"] == (
            ["tax_benefit_model_version_id", "parent_path", "reform_position"],
            True,
        )
        with v2_owner_sessions.begin() as session:
            assert (
                session.scalar(select(func.count()).select_from(ParameterTreeChild))
                == 0
            )
            parameter_id = session.scalars(
                select(col(Parameter.id)).where(
                    col(Parameter.tax_benefit_model_version_id) == version_id
                )
            ).one()
            for path, parent, position, child_type, child_count, reference in (
                ("gov", "", 0, "node", 1, None),
                ("gov.probe", "gov", 0, "node", 1, None),
                ("gov.probe.rate", "gov.probe", 0, "parameter", None, parameter_id),
            ):
                add_row(
                    session,
                    ParameterTreeChild,
                    id=uuid4(),
                    tax_benefit_model_version_id=version_id,
                    parent_path=parent,
                    path=path,
                    position=position,
                    label=path,
                    child_type=child_type,
                    child_count=child_count,
                    parameter_id=reference,
                )
            with refused(session):
                add_row(
                    session,
                    ParameterTreeChild,
                    id=uuid4(),
                    tax_benefit_model_version_id=version_id,
                    parent_path="gov",
                    path="gov.other",
                    position=0,
                    label="Other",
                    child_type="node",
                )
            session.execute(delete(Parameter).where(col(Parameter.id) == parameter_id))
            assert session.scalars(
                select(col(ParameterTreeChild.path)).order_by(
                    col(ParameterTreeChild.path)
                )
            ).all() == ["gov", "gov.probe"]

        command.downgrade(config, PARAMETER_TREE_PARENT_REVISION)

        assert (
            "parameter_tree_children"
            not in schema_inspector(v2_owner_sessions).get_table_names()
        )
        with v2_owner_sessions() as session:
            assert (
                session.scalar(
                    _version_row_count(VariableBeforeCatalogFormat2, version_id)
                )
                == 1
            )
    finally:
        command.upgrade(config, "head")
        _delete_probe_catalog(v2_owner_sessions)


PARAMETER_SEARCH_FILE_PARENT_REVISION = "3869eb814a90"


def test_parameter_search_file_table_is_created_empty_and_dropped_without_loss(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    """The search file revision creates an empty table and downgrades cleanly.

    The revision writes no rows: catalog publication writes each version's
    file. A version holds at most one file, the file is deleted with its
    version, and downgrading drops the table while every catalog row stays.
    """
    config = alembic_v2_config()
    try:
        command.downgrade(config, PARAMETER_SEARCH_FILE_PARENT_REVISION)
        assert (
            "parameter_search_files"
            not in schema_inspector(v2_owner_sessions).get_table_names()
        )
        with v2_owner_sessions.begin() as session:
            version_id = _catalog_version_published_before_format_2(session)

        command.upgrade(config, "head")

        file_values = {
            "tax_benefit_model_version_id": version_id,
            "file_format": 1,
            "compressed_content": b"\x1f\x8b compressed bytes",
            "content_sha256": "0" * 64,
            "uncompressed_size": 2,
            "compressed_size": 22,
        }
        with v2_owner_sessions.begin() as session:
            assert (
                session.scalar(select(func.count()).select_from(ParameterSearchFile))
                == 0
            )
            add_row(session, ParameterSearchFile, id=uuid4(), **file_values)
            with refused(session):
                add_row(session, ParameterSearchFile, id=uuid4(), **file_values)
            assert (
                session.scalars(
                    select(col(ParameterSearchFile.compressed_content)).where(
                        col(ParameterSearchFile.tax_benefit_model_version_id)
                        == version_id
                    )
                ).one()
                == file_values["compressed_content"]
            )

        command.downgrade(config, PARAMETER_SEARCH_FILE_PARENT_REVISION)

        assert (
            "parameter_search_files"
            not in schema_inspector(v2_owner_sessions).get_table_names()
        )
        with v2_owner_sessions() as session:
            assert (
                session.scalar(
                    _version_row_count(VariableBeforeCatalogFormat2, version_id)
                )
                == 1
            )

        command.upgrade(config, "head")
        with v2_owner_sessions.begin() as session:
            add_row(session, ParameterSearchFile, id=uuid4(), **file_values)
            session.execute(
                delete(TaxBenefitModelVersion).where(
                    col(TaxBenefitModelVersion.id) == version_id
                )
            )
            assert (
                session.scalar(select(func.count()).select_from(ParameterSearchFile))
                == 0
            )
    finally:
        command.upgrade(config, "head")
        _delete_probe_catalog(v2_owner_sessions)


CATALOG_PRUNING_PARENT_REVISION = "c614b6bcccfc"
CATALOG_PRUNING_COLUMNS = ("catalog_last_published_at", "catalog_values_pruned_at")


def _catalog_pruning_columns(session: Session, version_id: UUID) -> tuple[Any, Any]:
    last_published_at, values_pruned_at = session.execute(
        select(
            col(TaxBenefitModelVersion.catalog_last_published_at),
            col(TaxBenefitModelVersion.catalog_values_pruned_at),
        ).where(col(TaxBenefitModelVersion.id) == version_id)
    ).one()
    return last_published_at, values_pruned_at


def test_catalog_pruning_columns_are_added_null_and_dropped_without_loss(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    """The revision adds two null columns and downgrades cleanly.

    A stored version starts with neither a publication time nor a pruning
    time, both columns take timestamps, and downgrading drops only the two
    columns: the version and its rows stay. Upgrading again gives every
    version null in both.
    """
    config = alembic_v2_config()
    try:
        command.downgrade(config, CATALOG_PRUNING_PARENT_REVISION)
        for column_name in CATALOG_PRUNING_COLUMNS:
            assert column_name not in table_columns(
                v2_owner_sessions, "tax_benefit_model_versions"
            )
        with v2_owner_sessions.begin() as session:
            version_id = _catalog_version_published_before_format_2(session)

        command.upgrade(config, "head")

        with v2_owner_sessions.begin() as session:
            assert _catalog_pruning_columns(session, version_id) == (None, None)
            session.execute(
                update(TaxBenefitModelVersion)
                .where(col(TaxBenefitModelVersion.id) == version_id)
                .values(
                    catalog_last_published_at=func.now(),
                    catalog_values_pruned_at=func.now(),
                )
            )
            assert None not in _catalog_pruning_columns(session, version_id)

        command.downgrade(config, CATALOG_PRUNING_PARENT_REVISION)

        for column_name in CATALOG_PRUNING_COLUMNS:
            assert column_name not in table_columns(
                v2_owner_sessions, "tax_benefit_model_versions"
            )
        with v2_owner_sessions() as session:
            assert (
                session.scalars(
                    select(TaxBenefitModelVersionBeforeCatalogFormat2.version).where(
                        TaxBenefitModelVersionBeforeCatalogFormat2.id == version_id
                    )
                ).one()
                == "0.0.1-probe"
            )
            assert (
                session.scalar(
                    _version_row_count(ParameterBeforeCatalogFormat2, version_id)
                )
                == 1
            )

        command.upgrade(config, "head")
        with v2_owner_sessions() as session:
            assert _catalog_pruning_columns(session, version_id) == (None, None)
    finally:
        command.upgrade(config, "head")
        _delete_probe_catalog(v2_owner_sessions)

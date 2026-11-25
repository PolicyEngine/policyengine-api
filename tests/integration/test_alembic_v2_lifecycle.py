"""Exercise the isolated v2 Alembic lifecycle against disposable Postgres.

Every statement runs through a Session (rule api.data.orm-only). Rows written
at head use the v2 models. Rows written at an older revision use the small
mapped classes below, each on a declarative base of its own named after the
revision whose tables it maps, because the v2 models map head's columns. The
checks that a revision serves the release before it map that release's whole
schema with automap (``tests/integration/alembic_v2_previous_revision.py``).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy import delete, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql.base import PGInspector
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlmodel import col

from policyengine_api.data.v2.migration_target import (
    V2_ALEMBIC_HEAD_REVISION,
    V2MigrationTargetError,
)
from policyengine_api.data.v2.models import (
    V2_TABLE_NAMES,
    Country,
    Household,
    Report,
    ReportRun,
    Simulation,
    SimulationRun,
    Stage12ComparisonReport,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    User,
    UserHouseholdAssociation,
    UserReportAssociation,
)
from tests.fixtures.database_sessions import (
    create_registry_tables,
    drop_registry_tables,
    schema_inspector,
)
from tests.fixtures.integration.alembic_v2 import alembic_v2_config, table_columns
from tests.integration.alembic_v2_previous_revision import (
    ALEMBIC_VERSION_TABLE,
    assert_revision_serves_previous_revision,
)
from tests.integration.alembic_version_rows import current_revision
from tests.integration.simulation_rows import (
    RUN_VERSIONS,
    PublicApiRows,
    add_row,
    delete_public_api_rows,
    insert_public_api_rows,
    refused,
)

if TYPE_CHECKING:
    from alembic.config import Config
    from sqlalchemy.engine.interfaces import ReflectedForeignKeyConstraint
    from sqlalchemy.orm import Session, sessionmaker

BASELINE_REVISION = "f5ef4347cb2a"
STAGE_11_PREVIOUS_REVISION = "af34023a728f"
STAGE_12_PREVIOUS_REVISION = "724b1b11a33e"
STAGE_12_COMPARISON_PREVIOUS_REVISION = "439303be14fe"
STAGE_12A_PREVIOUS_REVISION = "91af4fc8d8c1"
STAGE_12A_REVISION = "fbb7488ebe8a"
COUNTRIES_PREVIOUS_REVISION = STAGE_12A_REVISION
COUNTRIES_REVISION = "fb1a3e40d3d6"
# The catalog format 2 revision, the parent of the area impact coordinate removal.
CATALOG_FORMAT_2_REVISION = "f5c1d9b4685b"
AREA_IMPACT_COORDINATE_REVISION = "e86f19a6c4da"
AREA_IMPACT_TABLES = ("constituency_impacts", "local_authority_impacts")
MAP_COORDINATE_COLUMNS = ("x", "y")


def _existing_enum(type_name: str) -> postgresql.ENUM:
    """Return the database's enum type ``type_name``, which these classes don't create.

    Rows name its values as text, which PostgreSQL checks against the type.
    """
    return postgresql.ENUM(name=type_name, create_type=False)


class BaselineBase(DeclarativeBase):
    """The declarative base of tables as the baseline revision created them."""


class TaxBenefitModelAtBaseline(BaselineBase):
    """A tax-benefit model's name at the baseline revision."""

    __tablename__ = "tax_benefit_models"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str]


class DatasetAtBaseline(BaselineBase):
    """A dataset at the baseline revision, which named its model directly."""

    __tablename__ = "datasets"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str]
    year: Mapped[int]
    is_output_dataset: Mapped[bool]
    tax_benefit_model_id: Mapped[UUID]


class RegionAtBaseline(BaselineBase):
    """A region at the baseline revision, with its required default dataset."""

    __tablename__ = "regions"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    code: Mapped[str]
    label: Mapped[str]
    region_type: Mapped[str] = mapped_column(_existing_enum("v2_region_type"))
    requires_filter: Mapped[bool]
    tax_benefit_model_id: Mapped[UUID]
    default_dataset_id: Mapped[UUID]


class Stage12ComparisonParentBase(DeclarativeBase):
    """The declarative base of tables as the Stage 12 comparison's parent left them."""


class Stage12ReportBeforeComparison(Stage12ComparisonParentBase):
    """A Stage 12 evaluation report's required columns, before comparison columns."""

    __tablename__ = "stage12_evaluation_reports"

    evaluation_id: Mapped[UUID] = mapped_column(primary_key=True)
    contract_version: Mapped[int]
    status: Mapped[str] = mapped_column(_existing_enum("v2_stage12_evaluation_status"))
    aggregation_status: Mapped[str] = mapped_column(
        _existing_enum("v2_stage12_aggregation_status")
    )
    environment: Mapped[str]
    calculation_flow: Mapped[str]
    originating_request_id: Mapped[str]
    production_identity: Mapped[str]
    worker_version: Mapped[str]
    modal_application: Mapped[str]
    report_coordinator_callable: Mapped[str]
    version_manifest_sha256: Mapped[str]
    policyengine_version: Mapped[str]
    country_package_name: Mapped[str]
    country_package_version: Mapped[str]
    country: Mapped[str]
    dataset_identity: Mapped[str]
    dataset_uri: Mapped[str]
    data_package_name: Mapped[str]
    data_package_version: Mapped[str]
    data_artifact_revision: Mapped[str]
    retention_expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))


class Stage12AParentBase(DeclarativeBase):
    """The declarative base of tables as the Stage 12A revision's parent left them."""


class UserBeforeStage12A(Stage12AParentBase):
    """A user before Stage 12A, when every user had a country."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    primary_country: Mapped[str]


class TaxBenefitModelBeforeStage12A(Stage12AParentBase):
    """A tax-benefit model's name before Stage 12A."""

    __tablename__ = "tax_benefit_models"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    name: Mapped[str]


class ReportBeforeStage12A(Stage12AParentBase):
    """A report's required columns before Stage 12A."""

    __tablename__ = "reports"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    label: Mapped[str]
    country: Mapped[str]
    tax_benefit_model_id: Mapped[UUID]
    inputs: Mapped[dict[str, Any]] = mapped_column(sa.JSON)


class UserReportAssociationBeforeStage12A(Stage12AParentBase):
    """A saved report before Stage 12A, which named a stored v2 report."""

    __tablename__ = "user_report_associations"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID]
    report_id: Mapped[UUID]
    country: Mapped[str]


class Stage12ABase(DeclarativeBase):
    """The declarative base of tables as the Stage 12A revision left them."""


class UserAtStage12A(Stage12ABase):
    """A user at Stage 12A, before the countries table."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    primary_country: Mapped[str | None]


class UserReportAssociationAtStage12A(Stage12ABase):
    """A saved report at Stage 12A, which may name an API v1 report instead."""

    __tablename__ = "user_report_associations"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID]
    country_id: Mapped[str]
    legacy_report_id: Mapped[int | None] = mapped_column(sa.BigInteger)


class UnreviewedTableBase(DeclarativeBase):
    """The declarative base of a table that no revision or v2 model declares."""


class UnreviewedRuntimeTable(UnreviewedTableBase):
    """A table created outside Alembic, which the upgrade to head must refuse."""

    __tablename__ = "unreviewed_runtime_table"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)


def _assert_head(sessions: sessionmaker[Session]) -> None:
    """Check the database is at head with exactly the v2 tables and its indexes.

    ``command.check``, which runs just before, compares the schema with the
    v2 models.
    """
    assert set(schema_inspector(sessions).get_table_names(schema="public")) == (
        V2_TABLE_NAMES | {ALEMBIC_VERSION_TABLE}
    )
    assert current_revision(sessions) == V2_ALEMBIC_HEAD_REVISION
    with sessions() as session:
        model_count = session.scalar(
            select(func.count())
            .select_from(TaxBenefitModel)
            .where(col(TaxBenefitModel.name) == "stage8-platform-validation")
        )
        version_count = session.scalar(
            select(func.count())
            .select_from(TaxBenefitModelVersion)
            .where(col(TaxBenefitModelVersion.version) == "stage8-platform-validation")
        )
    assert (model_count, version_count) == (0, 0)
    parameter_value_indexes = {
        index["name"]: index
        for index in schema_inspector(sessions).get_indexes("parameter_values")
    }
    canonical_index = parameter_value_indexes[
        "uq_parameter_values_canonical_parameter_start_date"
    ]
    assert canonical_index["unique"]
    assert canonical_index["column_names"] == ["parameter_id", "start_date"]
    policy_value_constraint = next(
        constraint
        for constraint in schema_inspector(sessions).get_unique_constraints(
            "parameter_values"
        )
        if constraint["name"] == "uq_parameter_values_policy_parameter_start_date"
    )
    assert policy_value_constraint["column_names"] == [
        "policy_id",
        "parameter_id",
        "start_date",
    ]
    assert {
        "legacy_household_mappings",
        "legacy_policy_mappings",
        "legacy_user_mappings",
        "legacy_user_policy_mappings",
    } <= set(schema_inspector(sessions).get_table_names(schema="public"))
    for table_name in AREA_IMPACT_TABLES:
        assert set(MAP_COORDINATE_COLUMNS).isdisjoint(
            table_columns(sessions, table_name)
        )


def _assert_area_impact_coordinates_restored(sessions: sessionmaker[Session]) -> None:
    """Check the catalog format 2 revision's map coordinates are required integers."""
    _assert_revision(sessions, CATALOG_FORMAT_2_REVISION)
    for table_name in AREA_IMPACT_TABLES:
        columns = table_columns(sessions, table_name)
        for column_name in MAP_COORDINATE_COLUMNS:
            assert isinstance(columns[column_name]["type"], sa.Integer)
            assert not columns[column_name]["nullable"]
            assert columns[column_name]["default"] is None


def _assert_pre_stage_12a_association_shape(sessions: sessionmaker[Session]) -> None:
    assert "user_identities" not in schema_inspector(sessions).get_table_names(
        schema="public"
    )
    for table_name, reference in (
        ("user_simulation_associations", "simulation"),
        ("user_report_associations", "report"),
    ):
        columns = table_columns(sessions, table_name)
        assert {"country", "label"} <= columns.keys()
        assert {
            "country_id",
            "name",
            f"legacy_{reference}_id",
        }.isdisjoint(columns)
        assert not columns[f"{reference}_id"]["nullable"]
        assert {
            foreign_key["referred_table"]
            for foreign_key in schema_inspector(sessions).get_foreign_keys(table_name)
        } == {"users", f"{reference}s"}
    for table_name, reference in (
        ("user_policies", "policy"),
        ("user_household_associations", "household"),
    ):
        columns = table_columns(sessions, table_name)
        assert f"legacy_{reference}_id" not in columns
        assert not columns[f"{reference}_id"]["nullable"]
    user_columns = table_columns(sessions, "users")
    assert "user_type" not in user_columns
    assert not user_columns["primary_country"]["nullable"]


def _assert_stage_12a_association_shape(sessions: sessionmaker[Session]) -> None:
    identity_constraints = {
        constraint["name"]: constraint["column_names"]
        for constraint in schema_inspector(sessions).get_unique_constraints(
            "user_identities"
        )
    }
    assert identity_constraints["uq_user_identities_issuer_subject"] == [
        "issuer",
        "subject",
    ]
    for table_name, reference in (
        ("user_policies", "policy"),
        ("user_household_associations", "household"),
        ("user_simulation_associations", "simulation"),
        ("user_report_associations", "report"),
    ):
        columns = table_columns(sessions, table_name)
        assert columns[f"{reference}_id"]["nullable"]
        assert columns[f"legacy_{reference}_id"]["nullable"]
        assert not columns["country_id"]["nullable"]
        assert "client_ref" not in columns
        # No uniqueness involves the owner, so a merge can move any row.
        assert [
            constraint["column_names"]
            for constraint in schema_inspector(sessions).get_unique_constraints(
                table_name
            )
        ] == [["id", "country_id"]]
    # At head, a saved simulation or report names a stored v2 simulation or
    # report through one RESTRICT key (revision 81b728a088e7).
    for table_name, column_name, referred_table in (
        ("user_simulation_associations", "simulation_id", "simulations"),
        ("user_report_associations", "report_id", "reports"),
    ):
        v2_record_keys = [
            (
                foreign_key["constrained_columns"],
                foreign_key["referred_table"],
                foreign_key["options"].get("ondelete"),
            )
            for foreign_key in schema_inspector(sessions).get_foreign_keys(table_name)
            if foreign_key["referred_table"] in {"simulations", "reports"}
        ]
        assert v2_record_keys == [([column_name], referred_table, "RESTRICT")]
    report_policy_key = next(
        foreign_key
        for foreign_key in schema_inspector(sessions).get_foreign_keys(
            "user_report_associations"
        )
        if foreign_key["referred_table"] == "user_policies"
    )
    assert report_policy_key["options"]["ondelete"] == "SET NULL"
    for table_name in ("user_simulation_associations", "user_report_associations"):
        columns = table_columns(sessions, table_name)
        assert columns["country"]["nullable"]
        assert columns["label"]["nullable"]
    user_columns = table_columns(sessions, "users")
    assert not user_columns["user_type"]["nullable"]
    user_type_default = user_columns["user_type"]["default"]
    assert user_type_default is not None
    assert "standard" in user_type_default
    assert user_columns["primary_country"]["nullable"]
    user_checks = _check_names(sessions, "users")
    # The user types revision renamed the type check when it added author and
    # admin.
    assert {
        "ck_users_user_type_allowed",
        "ck_users_standard_primary_country",
    } <= user_checks


def _upgrade_and_assert_head(config: Config, sessions: sessionmaker[Session]) -> None:
    command.upgrade(config, "head")
    command.check(config)
    _assert_head(sessions)


def _assert_revision(sessions: sessionmaker[Session], revision: str) -> None:
    assert current_revision(sessions) == revision


def _enum_type_names(sessions: sessionmaker[Session]) -> set[str]:
    """Return the name of every enum type in the database, in any schema."""
    inspector = schema_inspector(sessions)
    assert isinstance(inspector, PGInspector)
    return {enum_type["name"] for enum_type in inspector.get_enums(schema="*")}


def _assert_revision_without_enum_types(
    sessions: sessionmaker[Session], revision: str | None, enum_name_pattern: str
) -> None:
    """Check the database revision, then that no enum type's name matches.

    ``enum_name_pattern`` is a regular expression the whole name must match.
    """
    assert current_revision(sessions) == revision
    matching_enum_types = sorted(
        type_name
        for type_name in _enum_type_names(sessions)
        if re.fullmatch(enum_name_pattern, type_name)
    )
    assert matching_enum_types == []


def _insert_legacy_stage12_report(sessions: sessionmaker[Session]) -> UUID:
    """Store a report from before the comparison columns existed; return its id."""
    legacy_report_id = uuid4()
    with sessions.begin() as session:
        add_row(
            session,
            Stage12ReportBeforeComparison,
            evaluation_id=legacy_report_id,
            contract_version=1,
            status="pending",
            aggregation_status="not_started",
            environment="test",
            calculation_flow="economy",
            originating_request_id="request",
            production_identity="production",
            worker_version="5.2.0",
            modal_application="application",
            report_coordinator_callable="coordinate_report",
            version_manifest_sha256="a" * 64,
            policyengine_version="5.2.0",
            country_package_name="policyengine-us",
            country_package_version="1.0.0",
            country="us",
            dataset_identity="dataset",
            dataset_uri="hf://dataset/file@revision",
            data_package_name="data-package",
            data_package_version="1.0.0",
            data_artifact_revision="revision",
            # The database's clock, as created_at's server default uses.
            retention_expires_at=func.now() + timedelta(days=1),
        )
    return legacy_report_id


def _assert_comparison_downgrade_then_store_legacy_report(
    sessions: sessionmaker[Session],
) -> UUID:
    """Check the comparison revision is gone, then store a pre-comparison report."""
    _assert_revision_without_enum_types(
        sessions,
        STAGE_12_COMPARISON_PREVIOUS_REVISION,
        "v2_stage12_result_comparison_status",
    )
    report_columns = table_columns(sessions, "stage12_evaluation_reports")
    assert not any(name.startswith("comparison_") for name in report_columns)
    return _insert_legacy_stage12_report(sessions)


def _assert_legacy_report_is_not_compared(
    sessions: sessionmaker[Session], legacy_report_id: UUID
) -> None:
    with sessions() as session:
        comparison_status = session.scalars(
            select(col(Stage12ComparisonReport.comparison_status)).where(
                col(Stage12ComparisonReport.evaluation_id) == legacy_report_id
            )
        ).one()
    assert comparison_status == "not_requested"


def _assert_stage12_downgrade(sessions: sessionmaker[Session]) -> None:
    _assert_revision_without_enum_types(
        sessions, STAGE_12_PREVIOUS_REVISION, r"v2_stage12_.*"
    )
    assert {
        "stage12_evaluation_reports",
        "stage12_evaluation_simulations",
    }.isdisjoint(schema_inspector(sessions).get_table_names(schema="public"))


def _assert_stage11_downgrade(sessions: sessionmaker[Session]) -> None:
    _assert_revision(sessions, STAGE_11_PREVIOUS_REVISION)
    assert "legacy_household_mappings" not in schema_inspector(
        sessions
    ).get_table_names(schema="public")
    household_columns = table_columns(sessions, "households")
    assert {"country", "label", "year"} <= household_columns.keys()
    assert {
        "country_id",
        "default_year",
        "canonicalization_version",
        "content_hash",
    }.isdisjoint(household_columns)
    association_columns = table_columns(sessions, "user_household_associations")
    assert {"country", "label"} <= association_columns.keys()
    assert {"country_id", "name", "description"}.isdisjoint(association_columns)
    user_policy_id = table_columns(sessions, "user_policies")["user_id"]
    assert isinstance(user_policy_id["type"], postgresql.UUID)
    user_columns = table_columns(sessions, "users")
    assert all(
        user_columns[field_name]["nullable"]
        for field_name in ("first_name", "last_name", "email")
    )


def _assert_baseline_downgrade(sessions: sessionmaker[Session]) -> None:
    _assert_revision(sessions, BASELINE_REVISION)
    assert "uq_parameter_values_canonical_parameter_start_date" not in {
        index["name"]
        for index in schema_inspector(sessions).get_indexes("parameter_values")
    }


def _assert_base(sessions: sessionmaker[Session]) -> None:
    assert set(schema_inspector(sessions).get_table_names(schema="public")) <= {
        ALEMBIC_VERSION_TABLE
    }
    _assert_revision_without_enum_types(sessions, None, r"v2_.*")


# Every column that names a record's country, with the check it replaced.
COUNTRY_REFERENCE_COLUMNS = {
    ("users", "primary_country"): "ck_users_primary_country",
    ("households", "country_id"): "ck_households_country",
    ("policies", "country_id"): "ck_policies_country",
    ("user_household_associations", "country_id"): (
        "ck_user_household_associations_country"
    ),
    ("user_policies", "country_id"): "ck_user_policies_country",
    ("user_simulation_associations", "country_id"): (
        "ck_user_simulation_associations_country"
    ),
    ("user_report_associations", "country_id"): "ck_user_report_associations_country",
}
# The rows the countries revision inserts: the countries the replaced checks
# allowed, both household and society-wide capable.
LISTED_COUNTRIES = [("uk", True, True), ("us", True, True)]


def _country_foreign_keys(
    sessions: sessionmaker[Session], table_name: str
) -> list[ReflectedForeignKeyConstraint]:
    return [
        foreign_key
        for foreign_key in schema_inspector(sessions).get_foreign_keys(table_name)
        if foreign_key["referred_table"] == "countries"
    ]


def _check_names(sessions: sessionmaker[Session], table_name: str) -> set[str | None]:
    return {
        constraint["name"]
        for constraint in schema_inspector(sessions).get_check_constraints(table_name)
    }


def _listed_countries(sessions: sessionmaker[Session]) -> list[tuple[Any, ...]]:
    with sessions() as session:
        rows = session.execute(
            select(
                col(Country.id),
                col(Country.household_enabled),
                col(Country.society_wide_enabled),
            ).order_by(col(Country.id))
        ).all()
    return [tuple(row) for row in rows]


def _assert_countries_shape(sessions: sessionmaker[Session]) -> None:
    assert _listed_countries(sessions) == LISTED_COUNTRIES
    assert "ck_countries_society_wide_requires_household" in _check_names(
        sessions, "countries"
    )
    for (table_name, column_name), check_name in COUNTRY_REFERENCE_COLUMNS.items():
        country_keys = _country_foreign_keys(sessions, table_name)
        assert len(country_keys) == 1, table_name
        assert country_keys[0]["name"] == f"fk_{table_name}_{column_name}_countries"
        assert country_keys[0]["constrained_columns"] == [column_name]
        assert country_keys[0]["referred_columns"] == ["id"]
        assert country_keys[0]["options"]["ondelete"] == "RESTRICT"
        assert check_name not in _check_names(sessions, table_name)


def _assert_pre_countries_shape(sessions: sessionmaker[Session]) -> None:
    assert "countries" not in schema_inspector(sessions).get_table_names(
        schema="public"
    )
    for (table_name, _column_name), check_name in COUNTRY_REFERENCE_COLUMNS.items():
        assert _country_foreign_keys(sessions, table_name) == []
        assert check_name in _check_names(sessions, table_name)


def test_empty_upgrade_check_base_downgrade_and_reupgrade(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    config = alembic_v2_config()

    try:
        command.downgrade(config, "base")
        assert set(
            schema_inspector(v2_owner_sessions).get_table_names(schema="public")
        ) <= {ALEMBIC_VERSION_TABLE}

        _upgrade_and_assert_head(config, v2_owner_sessions)
        _assert_countries_shape(v2_owner_sessions)

        command.downgrade(config, CATALOG_FORMAT_2_REVISION)
        _assert_area_impact_coordinates_restored(v2_owner_sessions)
        _upgrade_and_assert_head(config, v2_owner_sessions)

        command.downgrade(config, COUNTRIES_PREVIOUS_REVISION)
        _assert_revision(v2_owner_sessions, COUNTRIES_PREVIOUS_REVISION)
        _assert_pre_countries_shape(v2_owner_sessions)
        _upgrade_and_assert_head(config, v2_owner_sessions)
        _assert_countries_shape(v2_owner_sessions)

        command.downgrade(config, STAGE_12A_PREVIOUS_REVISION)
        _assert_revision(v2_owner_sessions, STAGE_12A_PREVIOUS_REVISION)
        _assert_pre_stage_12a_association_shape(v2_owner_sessions)
        _upgrade_and_assert_head(config, v2_owner_sessions)
        _assert_stage_12a_association_shape(v2_owner_sessions)

        command.downgrade(config, STAGE_12_COMPARISON_PREVIOUS_REVISION)
        legacy_report_id = _assert_comparison_downgrade_then_store_legacy_report(
            v2_owner_sessions
        )
        _upgrade_and_assert_head(config, v2_owner_sessions)
        _assert_legacy_report_is_not_compared(v2_owner_sessions, legacy_report_id)

        command.downgrade(config, STAGE_12_PREVIOUS_REVISION)
        _assert_stage12_downgrade(v2_owner_sessions)
        _upgrade_and_assert_head(config, v2_owner_sessions)

        command.downgrade(config, STAGE_11_PREVIOUS_REVISION)
        _assert_stage11_downgrade(v2_owner_sessions)
        _upgrade_and_assert_head(config, v2_owner_sessions)

        command.downgrade(config, BASELINE_REVISION)
        _assert_baseline_downgrade(v2_owner_sessions)
        _upgrade_and_assert_head(config, v2_owner_sessions)

        command.downgrade(config, "base")
        _assert_base(v2_owner_sessions)
        _upgrade_and_assert_head(config, v2_owner_sessions)
    finally:
        command.upgrade(config, "head")


# Dormant at the Stage 12A parent revision: its models map these tables, and
# deleting a user cascades through them, but no parent-revision code inserts
# into them. They are the only tables Stage 12A may give a new required column.
STAGE_12A_PARENT_READ_ONLY_TABLES = frozenset(
    {"user_simulation_associations", "user_report_associations"}
)


def test_stage_12a_schema_serves_the_previous_revision(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    assert_revision_serves_previous_revision(
        v2_owner_sessions,
        STAGE_12A_PREVIOUS_REVISION,
        STAGE_12A_REVISION,
        STAGE_12A_PARENT_READ_ONLY_TABLES,
    )


def test_countries_schema_serves_the_previous_revision(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    """The release before the countries table keeps working during a deploy."""
    assert_revision_serves_previous_revision(
        v2_owner_sessions,
        COUNTRIES_PREVIOUS_REVISION,
        COUNTRIES_REVISION,
        frozenset(),
    )


def _column_names_by_table(sessions: sessionmaker[Session]) -> dict[str, set[str]]:
    """Return the names of every public table's columns, by the table's name."""
    inspector = schema_inspector(sessions)
    return {
        table_name: {column["name"] for column in inspector.get_columns(table_name)}
        for table_name in inspector.get_table_names()
    }


def test_area_impact_coordinate_removal_changes_nothing_else(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    """Check that the coordinate revision drops the map coordinates and nothing else.

    The revision is compared with its parent, the catalog format 2 revision. The
    previous API v1 revision still maps those four columns, but it can't
    read or write either table: no managed database role holds any privilege
    on them (``policyengine_api/data/v2/privileges.py``). Every table it can
    use keeps every column.
    """
    config = alembic_v2_config()

    try:
        command.downgrade(config, CATALOG_FORMAT_2_REVISION)
        parent = _column_names_by_table(v2_owner_sessions)
        command.upgrade(config, AREA_IMPACT_COORDINATE_REVISION)
        head = _column_names_by_table(v2_owner_sessions)

        assert set(head) == set(parent)
        dropped_columns = sorted(
            f"{table_name}.{column_name}"
            for table_name, column_names in parent.items()
            for column_name in column_names
            if column_name not in head[table_name]
        )
        added_columns = sorted(
            f"{table_name}.{column_name}"
            for table_name, column_names in head.items()
            for column_name in column_names
            if column_name not in parent[table_name]
        )
        assert dropped_columns == sorted(
            f"{table_name}.{column_name}"
            for table_name in AREA_IMPACT_TABLES
            for column_name in MAP_COORDINATE_COLUMNS
        )
        assert added_columns == []
    finally:
        command.upgrade(config, "head")


def test_upgrade_to_head_validates_the_resulting_schema_against_metadata(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    config = alembic_v2_config()

    try:
        command.downgrade(config, "base")
        with v2_owner_sessions.begin() as session:
            create_registry_tables(session, UnreviewedTableBase.registry)

        with pytest.raises(
            V2MigrationTargetError,
            match=r"v2 head schema.*unreviewed_runtime_table",
        ):
            command.upgrade(config, "head")

        assert current_revision(v2_owner_sessions) is None
    finally:
        with v2_owner_sessions.begin() as session:
            drop_registry_tables(session, UnreviewedTableBase.registry)
        command.upgrade(config, "head")


def test_baseline_uses_native_uuid_report_run_idempotency(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    config = alembic_v2_config()

    def idempotency_column_type() -> object:
        return table_columns(v2_owner_sessions, "report_runs")["idempotency_key"][
            "type"
        ]

    def report_run_checks() -> set[str | None]:
        return _check_names(v2_owner_sessions, "report_runs")

    report_id = uuid4()
    report_run_id = uuid4()
    simulation_id = uuid4()
    request_key = uuid4()
    public_api_rows: PublicApiRows | None = None
    try:
        command.upgrade(config, "head")
        assert isinstance(idempotency_column_type(), postgresql.UUID)
        assert "ck_report_runs_idempotency_key_nonblank" not in report_run_checks()

        with v2_owner_sessions.begin() as session:
            public_api_rows = insert_public_api_rows(session)
            add_row(
                session,
                Simulation,
                id=simulation_id,
                simulation_type="economy",
                dataset_id=public_api_rows.dataset_id,
                tax_benefit_model_version_id=public_api_rows.version_id,
            )
            simulation_run_id = uuid4()
            add_row(
                session,
                SimulationRun,
                id=simulation_run_id,
                simulation_id=simulation_id,
                tax_benefit_model_version_id=public_api_rows.version_id,
                year=2026,
                status="pending",
                **RUN_VERSIONS,
            )
            add_row(
                session,
                Report,
                id=report_id,
                country="us",
                tax_benefit_model_id=public_api_rows.model_id,
                inputs={},
            )
            add_row(
                session,
                ReportRun,
                id=report_run_id,
                report_id=report_id,
                baseline_simulation_run_id=simulation_run_id,
                country_package_version="1.0",
                policyengine_version="1.0",
                status="pending",
                # The key as text, which PostgreSQL stores as a native UUID.
                idempotency_key=str(request_key),
            )

        with v2_owner_sessions() as session:
            stored_key = session.scalars(
                select(col(ReportRun.idempotency_key)).where(
                    col(ReportRun.id) == report_run_id
                )
            ).one()
        assert stored_key == request_key
        assert isinstance(stored_key, UUID)
    finally:
        with v2_owner_sessions.begin() as session:
            session.execute(delete(ReportRun).where(col(ReportRun.id) == report_run_id))
            session.execute(delete(Report).where(col(Report.id) == report_id))
            session.execute(
                delete(Simulation).where(col(Simulation.id) == simulation_id)
            )
            if public_api_rows is not None:
                delete_public_api_rows(session, public_api_rows)
        command.upgrade(config, "head")


def test_baseline_region_default_enforces_same_model_dataset(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    config = alembic_v2_config()
    first_model_id = uuid4()
    second_model_id = uuid4()
    first_dataset_id = uuid4()
    second_dataset_id = uuid4()
    model_ids = (first_model_id, second_model_id)

    try:
        command.downgrade(config, BASELINE_REVISION)
        assert "region_datasets" not in schema_inspector(
            v2_owner_sessions
        ).get_table_names(schema="public")
        default_column = table_columns(v2_owner_sessions, "regions")[
            "default_dataset_id"
        ]
        assert not default_column["nullable"]
        default_constraint = next(
            constraint
            for constraint in schema_inspector(v2_owner_sessions).get_foreign_keys(
                "regions"
            )
            if constraint["name"] == "fk_regions_default_dataset_model_datasets"
        )
        assert default_constraint["constrained_columns"] == [
            "default_dataset_id",
            "tax_benefit_model_id",
        ]
        assert default_constraint["referred_columns"] == [
            "id",
            "tax_benefit_model_id",
        ]

        with v2_owner_sessions.begin() as session:
            for model_id in model_ids:
                add_row(
                    session,
                    TaxBenefitModelAtBaseline,
                    id=model_id,
                    name=f"region-default-{model_id.hex[:8]}",
                )
            for dataset_id, model_id in (
                (first_dataset_id, first_model_id),
                (second_dataset_id, second_model_id),
            ):
                add_row(
                    session,
                    DatasetAtBaseline,
                    id=dataset_id,
                    name="logical-input",
                    year=2024,
                    is_output_dataset=False,
                    tax_benefit_model_id=model_id,
                )
            add_row(
                session,
                RegionAtBaseline,
                id=uuid4(),
                code="us",
                label="United States",
                region_type="national",
                requires_filter=False,
                tax_benefit_model_id=first_model_id,
                default_dataset_id=first_dataset_id,
            )

        with pytest.raises(IntegrityError), v2_owner_sessions.begin() as session:
            add_row(
                session,
                RegionAtBaseline,
                id=uuid4(),
                code="state/ca",
                label="California",
                region_type="state",
                requires_filter=False,
                tax_benefit_model_id=first_model_id,
                default_dataset_id=second_dataset_id,
            )

        with pytest.raises(IntegrityError), v2_owner_sessions.begin() as session:
            add_row(
                session,
                DatasetAtBaseline,
                id=uuid4(),
                name="missing-output-path",
                year=2024,
                is_output_dataset=True,
                tax_benefit_model_id=first_model_id,
            )
    finally:
        with v2_owner_sessions.begin() as session:
            session.execute(
                delete(RegionAtBaseline).where(
                    RegionAtBaseline.tax_benefit_model_id.in_(model_ids)
                )
            )
            session.execute(
                delete(DatasetAtBaseline).where(
                    DatasetAtBaseline.tax_benefit_model_id.in_(model_ids)
                )
            )
            session.execute(
                delete(TaxBenefitModelAtBaseline).where(
                    TaxBenefitModelAtBaseline.id.in_(model_ids)
                )
            )
        command.upgrade(config, "head")


def test_stage_12a_reshape_refuses_retained_dormant_association_rows(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    """A retained pre-12A report association stops the reshape unchanged."""
    config = alembic_v2_config()
    user_id = uuid4()
    model_id = uuid4()
    report_id = uuid4()

    try:
        command.downgrade(config, STAGE_12A_PREVIOUS_REVISION)
        with v2_owner_sessions.begin() as session:
            add_row(session, UserBeforeStage12A, id=user_id, primary_country="us")
            add_row(
                session,
                TaxBenefitModelBeforeStage12A,
                id=model_id,
                name=f"stage12a-{model_id.hex[:8]}",
            )
            add_row(
                session,
                ReportBeforeStage12A,
                id=report_id,
                label="Stage 12A retained report",
                country="us",
                tax_benefit_model_id=model_id,
                inputs={},
            )
            add_row(
                session,
                UserReportAssociationBeforeStage12A,
                id=uuid4(),
                user_id=user_id,
                report_id=report_id,
                country="us",
            )

        with pytest.raises(IntegrityError):
            command.upgrade(config, "head")

        _assert_revision(v2_owner_sessions, STAGE_12A_PREVIOUS_REVISION)
        _assert_pre_stage_12a_association_shape(v2_owner_sessions)
    finally:
        with v2_owner_sessions.begin() as session:
            for model, row_id in (
                (UserBeforeStage12A, user_id),
                (ReportBeforeStage12A, report_id),
                (TaxBenefitModelBeforeStage12A, model_id),
            ):
                session.execute(delete(model).where(model.id == row_id))
        command.upgrade(config, "head")


def test_countries_revision_keeps_existing_rows_and_rejects_unlisted_countries(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    """Rows saved before the revision survive it, and only listed countries pass."""
    config = alembic_v2_config()
    user_id = uuid4()

    try:
        command.downgrade(config, COUNTRIES_PREVIOUS_REVISION)
        with v2_owner_sessions.begin() as session:
            add_row(session, UserAtStage12A, id=user_id, primary_country="uk")
            add_row(
                session,
                UserReportAssociationAtStage12A,
                id=uuid4(),
                user_id=user_id,
                country_id="uk",
                legacy_report_id=7,
            )

        command.upgrade(config, "head")
        command.check(config)
        _assert_countries_shape(v2_owner_sessions)

        with v2_owner_sessions() as session:
            stored_countries = session.execute(
                select(col(User.primary_country), col(UserReportAssociation.country_id))
                .join(
                    UserReportAssociation,
                    col(UserReportAssociation.user_id) == col(User.id),
                )
                .where(col(User.id) == user_id)
            ).one()
        assert tuple(stored_countries) == ("uk", "uk")

        with v2_owner_sessions() as session, refused(session):
            add_row(
                session,
                UserReportAssociation,
                id=uuid4(),
                user_id=user_id,
                country_id="ca",
                legacy_report_id=8,
            )

        with v2_owner_sessions() as session, refused(session):
            session.execute(delete(Country).where(col(Country.id) == "uk"))
    finally:
        with v2_owner_sessions.begin() as session:
            session.execute(delete(UserAtStage12A).where(UserAtStage12A.id == user_id))
        command.upgrade(config, "head")


def test_countries_downgrade_refuses_records_of_an_unlisted_country(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    """The restored US-and-UK checks stop a downgrade that would orphan records."""
    config = alembic_v2_config()
    user_id = uuid4()

    try:
        command.upgrade(config, "head")
        with v2_owner_sessions.begin() as session:
            add_row(
                session,
                Country,
                id="be",
                household_enabled=True,
                society_wide_enabled=False,
            )
            add_row(session, User, id=user_id, primary_country="be")

        with pytest.raises(IntegrityError):
            command.downgrade(config, COUNTRIES_PREVIOUS_REVISION)

        _assert_revision(v2_owner_sessions, V2_ALEMBIC_HEAD_REVISION)
    finally:
        with v2_owner_sessions.begin() as session:
            session.execute(delete(User).where(col(User.id) == user_id))
            session.execute(delete(Country).where(col(Country.id) == "be"))
        command.upgrade(config, "head")


def test_a_household_only_country_row_lets_records_name_that_country(
    v2_owner_sessions: sessionmaker[Session],
) -> None:
    """Once a household-only country has a row, its records can be stored."""
    config = alembic_v2_config()
    user_id = uuid4()
    household_id = uuid4()

    command.upgrade(config, "head")
    with v2_owner_sessions() as session:
        try:
            with refused(session):
                add_row(session, User, id=user_id, primary_country="be")

            add_row(
                session,
                Country,
                id="be",
                household_enabled=True,
                society_wide_enabled=False,
            )
            add_row(session, User, id=user_id, primary_country="be")
            add_row(
                session,
                Household,
                id=household_id,
                country_id="be",
                household_data={},
                canonicalization_version=1,
                content_hash="c" * 64,
            )
            add_row(
                session,
                UserHouseholdAssociation,
                id=uuid4(),
                user_id=user_id,
                household_id=household_id,
                country_id="be",
            )

            with refused(session):
                add_row(
                    session,
                    Country,
                    id="xx",
                    household_enabled=False,
                    society_wide_enabled=True,
                )
        finally:
            session.rollback()

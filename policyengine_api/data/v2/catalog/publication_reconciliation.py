"""Set-based reconciliation and validation for a staged v2 catalog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy import Select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped
from sqlmodel import col

from policyengine_api.data.v2.catalog.publication_inserts import column_type
from policyengine_api.data.v2.catalog.publication_staging_base import (
    StagedDataset,
    StagedModel,
    StagedParameter,
    StagedParameterNode,
    StagedParameterValue,
    StagedRegion,
    StagedVariable,
)
from policyengine_api.data.v2.catalog.publication_types import (
    CatalogPublicationError,
)
from policyengine_api.data.v2.models import (
    Dataset,
    DynamicParameter,
    DynamicParameterValue,
    Parameter,
    ParameterNode,
    ParameterValue,
    Region,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    Variable,
)

if TYPE_CHECKING:
    from uuid import UUID

    from sqlmodel import Session

    from policyengine_api.data.v2.catalog.records import CountryCatalog

# The catalog tables whose rows belong to one model version.
VersionedCatalogRow = (
    Variable | ParameterNode | Parameter | DynamicParameter | Dataset | Region
)
# A selected column: a mapped attribute, or an expression such as a cast.
ColumnExpression = sa.ColumnElement[Any] | Mapped[Any]


def version_exists(session: Session, country: CountryCatalog) -> bool:
    """Return whether the model name and version of this country are already stored."""
    statement = (
        sa.select(col(TaxBenefitModelVersion.id))
        .select_from(
            sa.join(
                TaxBenefitModelVersion,
                TaxBenefitModel,
                col(TaxBenefitModel.id) == col(TaxBenefitModelVersion.model_id),
            )
        )
        .where(
            col(TaxBenefitModel.name) == country.model.name,
            col(TaxBenefitModelVersion.version) == country.model_version.version,
        )
        .limit(1)
    )
    return session.execute(statement).first() is not None


def _versioned_from(model: type[VersionedCatalogRow]) -> sa.Join:
    """Join a catalog table to its rows' model version and model."""
    return sa.join(
        model,
        TaxBenefitModelVersion,
        col(TaxBenefitModelVersion.id) == col(model.tax_benefit_model_version_id),
    ).join(
        TaxBenefitModel,
        col(TaxBenefitModel.id) == col(TaxBenefitModelVersion.model_id),
    )


@dataclass(frozen=True, slots=True)
class StoredVersion:
    """A country's stored catalog version: its ID and catalog format.

    ``catalog_format`` is None for a version published before catalog format 2,
    whose format 2 fields are empty.
    """

    id: UUID
    catalog_format: int | None


def stored_version(session: Session, country: CountryCatalog) -> StoredVersion | None:
    """Return this country's stored catalog version, or None if it is not stored."""
    statement = (
        sa.select(
            col(TaxBenefitModelVersion.id), col(TaxBenefitModelVersion.catalog_format)
        )
        .select_from(
            sa.join(
                TaxBenefitModelVersion,
                TaxBenefitModel,
                col(TaxBenefitModel.id) == col(TaxBenefitModelVersion.model_id),
            )
        )
        .where(
            col(TaxBenefitModel.name) == country.model.name,
            col(TaxBenefitModelVersion.version) == country.model_version.version,
        )
    )
    row = session.execute(statement).one_or_none()
    if row is None:
        return None
    return StoredVersion(id=row.id, catalog_format=row.catalog_format)


def _comparison_pairs(
    country: CountryCatalog,
    *,
    with_format_2: bool,
) -> tuple[tuple[str, Select, Select], ...]:
    """Return each compared table's name with its staged and stored rows.

    Without ``with_format_2``, catalog format 2's fields are left out: a
    version published before format 2 keeps them empty, and publication never
    writes them on a stored version. The model version's
    ``metadata_time_periods`` are left out too: publication gives a stored
    version the staged ones (``update_stored_time_periods``).
    """

    def format_2(*columns: ColumnExpression) -> tuple[ColumnExpression, ...]:
        return columns if with_format_2 else ()

    staged_country = col(StagedModel.country_id) == country.country_id
    selected_version = sa.and_(
        col(TaxBenefitModel.name) == country.model.name,
        col(TaxBenefitModelVersion.version) == country.model_version.version,
    )

    staged_model_version = sa.select(
        col(StagedModel.version_description),
        col(StagedModel.current_law_id),
        *format_2(
            col(StagedModel.catalog_format),
            col(StagedModel.entities),
            col(StagedModel.basic_inputs),
        ),
    ).where(staged_country)
    actual_model_version = (
        sa.select(
            col(TaxBenefitModelVersion.description),
            col(TaxBenefitModelVersion.current_law_id),
            *format_2(
                col(TaxBenefitModelVersion.catalog_format),
                sa.cast(col(TaxBenefitModelVersion.entities), JSONB),
                sa.cast(col(TaxBenefitModelVersion.basic_inputs), JSONB),
            ),
        )
        .select_from(
            sa.join(
                TaxBenefitModelVersion,
                TaxBenefitModel,
                col(TaxBenefitModel.id) == col(TaxBenefitModelVersion.model_id),
            )
        )
        .where(selected_version)
    )

    staged_variables = sa.select(
        col(StagedVariable.name),
        col(StagedVariable.label),
        col(StagedVariable.entity),
        col(StagedVariable.description),
        col(StagedVariable.data_type),
        col(StagedVariable.possible_values),
        col(StagedVariable.default_value),
        col(StagedVariable.adds),
        col(StagedVariable.subtracts),
        *format_2(
            col(StagedVariable.is_input_variable),
            col(StagedVariable.hidden_input),
            col(StagedVariable.module_name),
            col(StagedVariable.adds_parameter_path),
            col(StagedVariable.subtracts_parameter_path),
            col(StagedVariable.enum_values),
            col(StagedVariable.unit),
            col(StagedVariable.definition_period),
        ),
    ).where(col(StagedVariable.country_id) == country.country_id)
    actual_variables = (
        sa.select(
            col(Variable.name),
            col(Variable.label),
            col(Variable.entity),
            col(Variable.description),
            col(Variable.data_type),
            sa.cast(col(Variable.possible_values), JSONB),
            sa.cast(col(Variable.default_value), JSONB),
            sa.cast(col(Variable.adds), JSONB),
            sa.cast(col(Variable.subtracts), JSONB),
            *format_2(
                col(Variable.is_input_variable),
                col(Variable.hidden_input),
                col(Variable.module_name),
                col(Variable.adds_parameter_path),
                col(Variable.subtracts_parameter_path),
                sa.cast(col(Variable.enum_values), JSONB),
                col(Variable.unit),
                col(Variable.definition_period),
            ),
        )
        .select_from(_versioned_from(Variable))
        .where(selected_version)
    )

    staged_parameter_nodes = sa.select(
        col(StagedParameterNode.name),
        col(StagedParameterNode.label),
        col(StagedParameterNode.description),
    ).where(col(StagedParameterNode.country_id) == country.country_id)
    actual_parameter_nodes = (
        sa.select(
            col(ParameterNode.name),
            col(ParameterNode.label),
            col(ParameterNode.description),
        )
        .select_from(_versioned_from(ParameterNode))
        .where(selected_version)
    )

    def staged_parameters(*, dynamic: bool) -> Select:
        return sa.select(
            col(StagedParameter.name),
            col(StagedParameter.label),
            col(StagedParameter.description),
            col(StagedParameter.data_type),
            col(StagedParameter.unit),
            *format_2(
                col(StagedParameter.economy),
                col(StagedParameter.household),
            ),
        ).where(
            col(StagedParameter.country_id) == country.country_id,
            col(StagedParameter.is_dynamic).is_(sa.true() if dynamic else sa.false()),
        )

    def actual_parameters(model: type[Parameter | DynamicParameter]) -> Select:
        return (
            sa.select(
                col(model.name),
                col(model.label),
                col(model.description),
                col(model.data_type),
                col(model.unit),
                *format_2(col(model.economy), col(model.household)),
            )
            .select_from(_versioned_from(model))
            .where(selected_version)
        )

    def staged_parameter_values(*, dynamic: bool) -> Select:
        """Select one kind of parameter's staged values, by its staged row."""
        return (
            sa.select(
                col(StagedParameterValue.parameter_name),
                col(StagedParameterValue.value_json),
                col(StagedParameterValue.start_date),
                col(StagedParameterValue.end_date),
            )
            .select_from(
                sa.join(
                    StagedParameterValue,
                    StagedParameter,
                    sa.and_(
                        col(StagedParameter.country_id)
                        == col(StagedParameterValue.country_id),
                        col(StagedParameter.name)
                        == col(StagedParameterValue.parameter_name),
                    ),
                )
            )
            .where(
                col(StagedParameterValue.country_id) == country.country_id,
                col(StagedParameter.is_dynamic).is_(
                    sa.true() if dynamic else sa.false()
                ),
            )
        )

    actual_dynamic_parameter_values = (
        sa.select(
            col(DynamicParameter.name),
            sa.cast(col(DynamicParameterValue.value_json), JSONB),
            col(DynamicParameterValue.start_date),
            col(DynamicParameterValue.end_date),
        )
        .select_from(
            sa.join(
                DynamicParameterValue,
                DynamicParameter,
                col(DynamicParameter.id)
                == col(DynamicParameterValue.dynamic_parameter_id),
            )
            .join(
                TaxBenefitModelVersion,
                col(TaxBenefitModelVersion.id)
                == col(DynamicParameter.tax_benefit_model_version_id),
            )
            .join(
                TaxBenefitModel,
                col(TaxBenefitModel.id) == col(TaxBenefitModelVersion.model_id),
            )
        )
        .where(selected_version, col(DynamicParameterValue.dynamic_id).is_(None))
    )
    actual_parameter_values = (
        sa.select(
            col(Parameter.name),
            sa.cast(col(ParameterValue.value_json), JSONB),
            col(ParameterValue.start_date),
            col(ParameterValue.end_date),
        )
        .select_from(
            sa.join(
                ParameterValue,
                Parameter,
                col(Parameter.id) == col(ParameterValue.parameter_id),
            )
            .join(
                TaxBenefitModelVersion,
                col(TaxBenefitModelVersion.id)
                == col(Parameter.tax_benefit_model_version_id),
            )
            .join(
                TaxBenefitModel,
                col(TaxBenefitModel.id) == col(TaxBenefitModelVersion.model_id),
            )
        )
        .where(
            selected_version,
            col(ParameterValue.policy_id).is_(None),
            col(ParameterValue.dynamic_id).is_(None),
        )
    )

    staged_datasets = sa.select(
        col(StagedDataset.name),
        col(StagedDataset.description),
        col(StagedDataset.year),
        sa.literal(value=False),
        sa.cast(sa.null(), column_type(Dataset, "storage_path")),
    ).where(col(StagedDataset.country_id) == country.country_id)
    actual_datasets = (
        sa.select(
            col(Dataset.name),
            col(Dataset.description),
            col(Dataset.year),
            col(Dataset.is_output_dataset),
            col(Dataset.storage_path),
        )
        .select_from(_versioned_from(Dataset))
        .where(
            selected_version,
            col(Dataset.is_output_dataset).is_(False),
            col(Dataset.storage_path).is_(None),
        )
    )

    return (
        ("model version", staged_model_version, actual_model_version),
        ("variables", staged_variables, actual_variables),
        ("parameter nodes", staged_parameter_nodes, actual_parameter_nodes),
        (
            "parameters",
            staged_parameters(dynamic=False),
            actual_parameters(Parameter),
        ),
        (
            "dynamic parameters",
            staged_parameters(dynamic=True),
            actual_parameters(DynamicParameter),
        ),
        (
            "parameter values",
            staged_parameter_values(dynamic=False),
            actual_parameter_values,
        ),
        (
            "dynamic parameter values",
            staged_parameter_values(dynamic=True),
            actual_dynamic_parameter_values,
        ),
        ("datasets", staged_datasets, actual_datasets),
    )


def _region_comparison_pair(country: CountryCatalog) -> tuple[Select, Select]:
    """Return the staged and stored region rows of one country's catalog version."""
    selected_version = sa.and_(
        col(TaxBenefitModel.name) == country.model.name,
        col(TaxBenefitModelVersion.version) == country.model_version.version,
    )
    staged_regions = sa.select(
        col(StagedRegion.code),
        col(StagedRegion.label),
        col(StagedRegion.region_type),
        col(StagedRegion.requires_filter),
        col(StagedRegion.filter_field),
        col(StagedRegion.filter_value),
        col(StagedRegion.filter_strategy),
        col(StagedRegion.parent_code),
        col(StagedRegion.state_code),
        col(StagedRegion.state_name),
        col(StagedRegion.default_dataset_name),
    ).where(col(StagedRegion.country_id) == country.country_id)
    actual_regions = (
        sa.select(
            col(Region.code),
            col(Region.label),
            sa.cast(col(Region.region_type), sa.Text),
            col(Region.requires_filter),
            col(Region.filter_field),
            col(Region.filter_value),
            col(Region.filter_strategy),
            col(Region.parent_code),
            col(Region.state_code),
            col(Region.state_name),
            col(Dataset.name),
        )
        .select_from(
            _versioned_from(Region).join(
                Dataset,
                col(Dataset.id) == col(Region.default_dataset_id),
            )
        )
        .where(selected_version)
    )

    return staged_regions, actual_regions


def _sets_differ(
    session: Session,
    staged: Select,
    actual: Select,
) -> bool:
    missing = sa.except_(staged, actual).subquery()
    extra = sa.except_(actual, staged).subquery()
    differences = sa.union_all(
        sa.select(sa.literal(1)).select_from(missing),
        sa.select(sa.literal(1)).select_from(extra),
    ).limit(1)
    return session.execute(differences).first() is not None


def assert_country_matches(
    session: Session,
    country: CountryCatalog,
    *,
    include_regions: bool = True,
) -> None:
    """Raise CatalogPublicationError if the stored version differs from the staged one.

    Rows are compared as sets in both directions, so a missing row and an extra
    row both fail; the error names the first table that differs, never its
    rows. Without ``include_regions``, region rows are not compared: they come
    from API v1's reference files, which may change while the
    PolicyEngine.py version stays the same. The model version's
    ``metadata_time_periods`` are never compared, for the same reason: they
    come from ``policyengine_api.economy_years``. A version published before
    catalog format 2 is compared without format 2's fields.
    """
    stored = stored_version(session, country)
    pairs = _comparison_pairs(
        country,
        with_format_2=stored is not None and stored.catalog_format is not None,
    )
    if include_regions:
        pairs = (*pairs, ("regions", *_region_comparison_pair(country)))
    for table_name, staged, actual in pairs:
        if _sets_differ(session, staged, actual):
            msg = (
                f"the stored {country.country_id} catalog version "
                f"{country.model_version.version} differs from the staged catalog "
                f"in its {table_name}"
            )
            raise CatalogPublicationError(msg)


def update_stored_time_periods(
    session: Session, country: CountryCatalog
) -> tuple[list[int], list[int]] | None:
    """Give this country's stored version the staged ``metadata_time_periods``.

    They are the years API v1 offers for the version, which come from
    ``policyengine_api.economy_years`` and so may change while the
    PolicyEngine.py version stays the same. When the two lists differ, a
    change of order included, replace the stored list in the publication's
    transaction and return the stored and staged lists; return None when they
    are equal. Raise CatalogPublicationError if the version is not stored or
    the country was not staged.
    """
    staged_time_periods = (
        sa.select(col(StagedModel.metadata_time_periods))
        .where(col(StagedModel.country_id) == country.country_id)
        .scalar_subquery()
    )
    row = session.execute(
        sa.select(
            col(TaxBenefitModelVersion.id),
            sa.cast(col(TaxBenefitModelVersion.metadata_time_periods), JSONB).label(
                "stored"
            ),
            staged_time_periods.label("staged"),
        )
        .select_from(
            sa.join(
                TaxBenefitModelVersion,
                TaxBenefitModel,
                col(TaxBenefitModel.id) == col(TaxBenefitModelVersion.model_id),
            )
        )
        .where(
            col(TaxBenefitModel.name) == country.model.name,
            col(TaxBenefitModelVersion.version) == country.model_version.version,
        )
    ).one_or_none()
    if row is None or row.staged is None:
        msg = (
            f"the {country.country_id} catalog version "
            f"{country.model_version.version} has no stored or no staged "
            "time periods"
        )
        raise CatalogPublicationError(msg)
    if row.stored == row.staged:
        return None
    session.execute(
        sa.update(TaxBenefitModelVersion)
        .where(col(TaxBenefitModelVersion.id) == row.id)
        .values(metadata_time_periods=row.staged)
        .execution_options(synchronize_session=False)
    )
    return list(row.stored), list(row.staged)


def count_stored_regions(session: Session, country: CountryCatalog) -> int:
    """Count the region rows stored for one country's catalog version."""
    _staged, actual = _region_comparison_pair(country)
    count: int = session.execute(
        sa.select(sa.func.count()).select_from(actual.subquery())
    ).scalar_one()
    return count


def count_region_differences(
    session: Session,
    country: CountryCatalog,
) -> tuple[int, int]:
    """Count staged region rows the stored version lacks, and stored rows not staged."""
    staged, actual = _region_comparison_pair(country)
    staged_not_stored = sa.except_(staged, actual).subquery()
    stored_not_staged = sa.except_(actual, staged).subquery()
    return (
        session.execute(
            sa.select(sa.func.count()).select_from(staged_not_stored)
        ).scalar_one(),
        session.execute(
            sa.select(sa.func.count()).select_from(stored_not_staged)
        ).scalar_one(),
    )


def assert_canonical_value_uniqueness(session: Session) -> None:
    """Raise CatalogPublicationError if a parameter has duplicate current-law values.

    Current-law values are those with neither a policy nor a dynamic, in
    either table; each parameter may have only one per start date.
    """
    duplicates = (
        sa.select(col(ParameterValue.parameter_id))
        .where(
            col(ParameterValue.policy_id).is_(None),
            col(ParameterValue.dynamic_id).is_(None),
        )
        .group_by(
            col(ParameterValue.parameter_id),
            col(ParameterValue.start_date),
        )
        .having(sa.func.count() > 1)
        .limit(1)
    )
    dynamic_duplicates = (
        sa.select(col(DynamicParameterValue.dynamic_parameter_id))
        .where(col(DynamicParameterValue.dynamic_id).is_(None))
        .group_by(
            col(DynamicParameterValue.dynamic_parameter_id),
            col(DynamicParameterValue.start_date),
        )
        .having(sa.func.count() > 1)
        .limit(1)
    )
    if (
        session.execute(duplicates).first() is not None
        or session.execute(dynamic_duplicates).first() is not None
    ):
        msg = "canonical parameter-value uniqueness validation failed"
        raise CatalogPublicationError(msg)

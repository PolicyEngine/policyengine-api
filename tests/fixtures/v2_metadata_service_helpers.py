"""Helpers that store v2 catalog versions and read them through the metadata service."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import event
from sqlmodel import Session, select

from policyengine_api.data.v2.models import (
    Dataset,
    Parameter,
    ParameterNode,
    ParameterValue,
    Region,
    RegionType,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    Variable,
)
from policyengine_api.services.v2.metadata.database_session import (
    MetadataDatabaseSession,
)
from policyengine_api.services.v2.metadata.services import V2MetadataService
from tests.fixtures.v2_catalog import POLICYENGINE_VERSION, normalized_catalog

if TYPE_CHECKING:
    from policyengine_api.services.v2.metadata.selected_catalogs import (
        SelectedCatalogStore,
    )


def insert_country(
    session: Session,
    country,
    *,
    include_model: bool,
    current_law_id: int | None = None,
    time_periods: list[int] | None = None,
) -> None:
    if include_model:
        session.add(
            TaxBenefitModel(
                id=country.model.id,
                name=country.model.name,
                description=country.model.description,
            )
        )
    session.add(
        TaxBenefitModelVersion(
            id=country.model_version.id,
            model_id=country.model.id,
            version=country.model_version.version,
            description=country.model_version.description,
            current_law_id=(
                country.model_version.current_law_id
                if current_law_id is None
                else current_law_id
            ),
            metadata_time_periods=(
                list(country.model_version.metadata_time_periods)
                if time_periods is None
                else time_periods
            ),
            catalog_format=country.model_version.catalog_format,
            entities=[
                {
                    "key": entity.key,
                    "plural": entity.plural,
                    "is_person": entity.is_person,
                }
                for entity in country.model_version.entities
            ],
            basic_inputs=list(country.model_version.basic_inputs),
        )
    )
    session.add_all(
        Variable(
            id=record.id,
            tax_benefit_model_version_id=country.model_version.id,
            name=record.name,
            label=record.label,
            entity=record.entity,
            description=record.description,
            data_type=record.data_type,
            possible_values=record.possible_values,
            default_value=record.default_value,
            adds=record.adds,
            subtracts=record.subtracts,
            is_input_variable=record.is_input_variable,
            hidden_input=record.hidden_input,
            module_name=record.module_name,
            adds_parameter_path=record.adds_parameter_path,
            subtracts_parameter_path=record.subtracts_parameter_path,
            enum_values=(
                None
                if record.enum_values is None
                else [
                    {"value": enum_value.value, "label": enum_value.label}
                    for enum_value in record.enum_values
                ]
            ),
            unit=record.unit,
            definition_period=record.definition_period,
        )
        for record in country.variables
    )
    session.add_all(
        ParameterNode(
            id=record.id,
            tax_benefit_model_version_id=country.model_version.id,
            name=record.name,
            label=record.label,
            description=record.description,
        )
        for record in country.parameter_nodes
    )
    session.add_all(
        Parameter(
            id=record.id,
            tax_benefit_model_version_id=country.model_version.id,
            name=record.name,
            label=record.label,
            description=record.description,
            data_type=record.data_type,
            unit=record.unit,
            economy=record.economy,
            household=record.household,
        )
        for record in country.parameters
    )
    session.add_all(
        ParameterValue(
            id=value.id,
            parameter_id=value.parameter_id,
            value_json=value.value_json,
            start_date=value.start_date,
            end_date=value.end_date,
        )
        for parameter in country.parameters
        for value in parameter.values
    )
    session.add_all(
        Dataset(
            id=record.id,
            tax_benefit_model_version_id=country.model_version.id,
            name=record.name,
            description=record.description,
            year=record.year,
        )
        for record in country.datasets
    )
    session.add_all(
        Region(
            id=record.id,
            tax_benefit_model_version_id=country.model_version.id,
            default_dataset_id=record.default_dataset_id,
            code=record.code,
            label=record.label,
            region_type=RegionType(record.region_type),
            requires_filter=record.requires_filter,
            filter_field=record.filter_field,
            filter_value=record.filter_value,
            filter_strategy=record.filter_strategy,
            parent_code=record.parent_code,
            state_code=record.state_code,
            state_name=record.state_name,
        )
        for record in country.regions
    )


def add_country_version(
    session: Session,
    *,
    policyengine_version: str,
    current_law_id: int,
    time_periods: list[int],
) -> None:
    country = normalized_catalog(policyengine_version=policyengine_version).country(
        "us"
    )
    insert_country(
        session,
        country,
        include_model=False,
        current_law_id=current_law_id,
        time_periods=time_periods,
    )
    session.commit()


def stored_model_version(
    session: Session, model_name: str, version: str = POLICYENGINE_VERSION
) -> TaxBenefitModelVersion:
    return session.exec(
        select(TaxBenefitModelVersion)
        .join(TaxBenefitModel, TaxBenefitModel.id == TaxBenefitModelVersion.model_id)
        .where(
            TaxBenefitModel.name == model_name,
            TaxBenefitModelVersion.version == version,
        )
    ).one()


def catalog_service(
    session: Session, *, selected_catalogs: SelectedCatalogStore | None = None
) -> V2MetadataService:
    return V2MetadataService(
        MetadataDatabaseSession(session),
        running_policyengine_version=POLICYENGINE_VERSION,
        selected_catalogs=selected_catalogs,
    )


def recorded_statements(session: Session, read):
    statements: list[str] = []

    def record_statement(_connection, _cursor, statement, *_args) -> None:
        statements.append(statement.lower())

    bind = session.get_bind()
    event.listen(bind, "before_cursor_execute", record_statement)
    try:
        result = read()
    finally:
        event.remove(bind, "before_cursor_execute", record_statement)
    return result, statements

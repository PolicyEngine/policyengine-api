"""Typed read-only query coverage for the v2 metadata preview."""

from __future__ import annotations

import ast
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, select

from policyengine_api.data.v2.catalog.query import (
    InvalidPolicyEngineVersionError,
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
    UnsupportedPreviewCountryError,
    V2MetadataQueryService,
)
from policyengine_api.data.v2.catalog.schemas import (
    MetadataErrorResponse,
    MetadataPreviewResponse,
    MetadataSuccessResponse,
)
from policyengine_api.data.v2.models import (
    Dataset,
    Parameter,
    ParameterNode,
    ParameterValue,
    Region,
    RegionType,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    V2_METADATA,
    Variable,
)
from tests.fixtures.v2_catalog import POLICYENGINE_VERSION, normalized_catalog


@pytest.fixture
def catalog_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    V2_METADATA.create_all(engine)
    catalog = normalized_catalog()
    with Session(engine) as session:
        for country in catalog.countries:
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
                    current_law_id=country.model_version.current_law_id,
                    metadata_time_periods=list(
                        country.model_version.metadata_time_periods
                    ),
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
        session.commit()

    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _add_country_version(
    session: Session,
    *,
    policyengine_version: str,
    current_law_id: int,
    time_periods: list[int],
) -> None:
    country = normalized_catalog(policyengine_version=policyengine_version).country(
        "us"
    )
    session.add(
        TaxBenefitModelVersion(
            id=country.model_version.id,
            model_id=country.model.id,
            version=policyengine_version,
            description=f"US model for {policyengine_version}",
            current_law_id=current_law_id,
            metadata_time_periods=time_periods,
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
            description=f"{record.description} for {policyengine_version}",
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
            label=f"{record.label} {policyengine_version}",
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
    session.commit()


def test_query_serializes_complete_typed_metadata_without_writes(
    catalog_session: Session,
) -> None:
    service = V2MetadataQueryService(
        catalog_session,
        running_policyengine_version=POLICYENGINE_VERSION,
    )
    model_classes = (
        TaxBenefitModel,
        TaxBenefitModelVersion,
        Variable,
        ParameterNode,
        Parameter,
        ParameterValue,
        Dataset,
        Region,
    )
    before = {
        model_class.__tablename__: len(catalog_session.exec(select(model_class)).all())
        for model_class in model_classes
    }

    result = service.get_metadata("us")

    assert result.current_law_id == 2
    assert result.model.name == "policyengine-us"
    assert result.model_version.version == POLICYENGINE_VERSION
    assert [variable.name for variable in result.variables] == ["employment_income"]
    assert [parameter.name for parameter in result.parameters] == ["gov.example.rate"]
    assert [value.value for value in result.parameters[0].values] == [0.1, 0.2]
    assert {dataset.name for dataset in result.datasets} == {
        "populace_us_2024",
        "populace_us_ca_2024",
    }
    assert all(not dataset.is_output_dataset for dataset in result.datasets)
    assert all(dataset.storage_path is None for dataset in result.datasets)
    assert result.economy_options.region[0].name == "place/CA-44000"
    assert result.economy_options.time_period[0].name == 2035
    assert result.economy_options.time_period[-1].name == 2022
    assert [option.name for option in result.economy_options.datasets] == [
        "populace_us_2024"
    ]
    assert [option.label for option in result.economy_options.datasets] == ["Microcosm"]
    after = {
        model_class.__tablename__: len(catalog_session.exec(select(model_class)).all())
        for model_class in model_classes
    }
    assert after == before


def test_query_excludes_output_datasets(catalog_session: Session) -> None:
    model = catalog_session.exec(
        select(TaxBenefitModel).where(TaxBenefitModel.name == "policyengine-us")
    ).one()
    catalog_session.add(
        Dataset(
            id=uuid4(),
            tax_benefit_model_version_id=catalog_session.exec(
                select(TaxBenefitModelVersion).where(
                    TaxBenefitModelVersion.model_id == model.id,
                    TaxBenefitModelVersion.version == POLICYENGINE_VERSION,
                )
            )
            .one()
            .id,
            name="simulation-output",
            description="Generated result",
            storage_path="private-output-reference",
            year=2026,
            is_output_dataset=True,
        )
    )
    catalog_session.commit()

    result = V2MetadataQueryService(
        catalog_session,
        running_policyengine_version=POLICYENGINE_VERSION,
    ).get_metadata("us")

    assert "simulation-output" not in {dataset.name for dataset in result.datasets}


def test_query_defaults_to_running_version_and_allows_exact_override(
    catalog_session: Session,
) -> None:
    _add_country_version(
        catalog_session,
        policyengine_version="5.0.5",
        current_law_id=22,
        time_periods=[2041, 2040],
    )
    service = V2MetadataQueryService(
        catalog_session,
        running_policyengine_version=POLICYENGINE_VERSION,
    )

    default = service.get_metadata("us")
    selected = service.get_metadata("us", "5.0.5")

    assert default.model_version.version == POLICYENGINE_VERSION
    assert default.current_law_id == 2
    assert default.economy_options.time_period[0].name == 2035
    assert selected.model_version.version == "5.0.5"
    assert selected.model.description == "US model for 5.0.5"
    assert selected.current_law_id == 22
    assert [option.name for option in selected.economy_options.time_period] == [
        2041,
        2040,
    ]
    assert {dataset.id for dataset in default.datasets}.isdisjoint(
        dataset.id for dataset in selected.datasets
    )
    assert {region.id for region in default.regions}.isdisjoint(
        region.id for region in selected.regions
    )


def test_query_rejects_invalid_or_absent_selected_versions(
    catalog_session: Session,
) -> None:
    service = V2MetadataQueryService(
        catalog_session,
        running_policyengine_version=POLICYENGINE_VERSION,
    )

    for invalid in ("", f" {POLICYENGINE_VERSION}", "not a version", "0.0.0"):
        with pytest.raises(InvalidPolicyEngineVersionError):
            service.get_metadata("us", invalid)
    with pytest.raises(MetadataCatalogVersionNotFoundError):
        service.get_metadata("us", "4.99.0")
    with pytest.raises(MetadataCatalogUnavailableError):
        V2MetadataQueryService(
            catalog_session,
            running_policyengine_version="4.99.0",
        ).get_metadata("us")


def test_query_rejects_unsupported_and_incomplete_catalogs(
    catalog_session: Session,
) -> None:
    service = V2MetadataQueryService(
        catalog_session,
        running_policyengine_version=POLICYENGINE_VERSION,
    )
    with pytest.raises(UnsupportedPreviewCountryError):
        service.get_metadata("ca")

    uk_model = catalog_session.exec(
        select(TaxBenefitModel).where(TaxBenefitModel.name == "policyengine-uk")
    ).one()
    uk_model_version = catalog_session.exec(
        select(TaxBenefitModelVersion).where(
            TaxBenefitModelVersion.model_id == uk_model.id,
            TaxBenefitModelVersion.version == POLICYENGINE_VERSION,
        )
    ).one()
    for region in catalog_session.exec(
        select(Region).where(Region.tax_benefit_model_version_id == uk_model_version.id)
    ).all():
        catalog_session.delete(region)
    catalog_session.commit()
    with pytest.raises(MetadataCatalogUnavailableError, match="incomplete"):
        service.get_metadata("uk")


def test_query_rejects_incomplete_parameter_values(
    catalog_session: Session,
) -> None:
    us_model_version = catalog_session.exec(
        select(TaxBenefitModelVersion)
        .join(TaxBenefitModel, TaxBenefitModel.id == TaxBenefitModelVersion.model_id)
        .where(
            TaxBenefitModel.name == "policyengine-us",
            TaxBenefitModelVersion.version == POLICYENGINE_VERSION,
        )
    ).one()
    us_parameter_ids = set(
        catalog_session.exec(
            select(Parameter.id).where(
                Parameter.tax_benefit_model_version_id == us_model_version.id
            )
        ).all()
    )
    for value in catalog_session.exec(
        select(ParameterValue).where(ParameterValue.parameter_id.in_(us_parameter_ids))
    ).all():
        catalog_session.delete(value)
    catalog_session.commit()

    service = V2MetadataQueryService(
        catalog_session,
        running_policyengine_version=POLICYENGINE_VERSION,
    )
    with pytest.raises(
        MetadataCatalogUnavailableError,
        match="parameter values are incomplete",
    ):
        service.get_metadata("us")


def test_response_outcomes_are_discriminated_and_strict(
    catalog_session: Session,
) -> None:
    result = V2MetadataQueryService(
        catalog_session,
        running_policyengine_version=POLICYENGINE_VERSION,
    ).get_metadata("uk")
    adapter = TypeAdapter(MetadataPreviewResponse)

    success = adapter.validate_python(
        MetadataSuccessResponse(result=result).model_dump()
    )
    error = adapter.validate_python(
        MetadataErrorResponse(message="Catalog unavailable").model_dump()
    )
    assert success.status == "ok"
    assert error.status == "error"

    with pytest.raises(ValidationError):
        adapter.validate_python({"status": "ok", "message": None})
    with pytest.raises(ValidationError):
        adapter.validate_python({"status": "error", "message": ""})
    with pytest.raises(ValidationError):
        adapter.validate_python({"status": "error", "message": "   "})
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {
                "status": "error",
                "message": "Failure",
                "result": result.model_dump(),
            }
        )
    with pytest.raises(ValidationError):
        adapter.validate_python({"status": "pending", "message": "Wait"})


def test_query_module_imports_no_policyengine_or_v1_metadata_source() -> None:
    source_path = (
        Path(__file__).parents[3]
        / "policyengine_api"
        / "data"
        / "v2"
        / "catalog"
        / "query.py"
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert not any(
        module.startswith(
            (
                "policyengine_core",
                "policyengine_us",
                "policyengine_uk",
                "policyengine_api.country",
                "policyengine_api.services.metadata_service",
                "policyengine_api.data.v2.catalog.extraction",
            )
        )
        for module in imported
    )

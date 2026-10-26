"""Read-only service coverage for v2 metadata resources."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, select

from policyengine_api.data.v2.catalog.catalog_selection import (
    InvalidPolicyEngineVersionError,
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
    UnsupportedPreviewCountryError,
)
from policyengine_api.data.v2.models import (
    V2_METADATA,
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
from policyengine_api.services.v2.metadata.selected_catalogs import (
    SelectedCatalogStore,
)
from policyengine_api.services.v2.metadata.services import V2MetadataService
from policyengine_api.services.v2.metadata.transformations import ancestor_paths
from policyengine_api.services.v2.metadata.types import (
    MetadataDatedValue,
    MetadataEntity,
    MetadataEnumValue,
    ParameterFilter,
    ParameterValueFilter,
)
from policyengine_api.services.v2.metadata.validators import (
    InvalidMetadataPageError,
    MetadataResourceNotFoundError,
)
from tests.fixtures.v2_catalog import POLICYENGINE_VERSION, normalized_catalog


def _insert_country(
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


@pytest.fixture
def catalog_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    V2_METADATA.create_all(engine)
    with Session(engine) as session:
        for country in normalized_catalog().countries:
            _insert_country(session, country, include_model=True)
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
    _insert_country(
        session,
        country,
        include_model=False,
        current_law_id=current_law_id,
        time_periods=time_periods,
    )
    session.commit()


def _us_model_version(session: Session) -> TaxBenefitModelVersion:
    return session.exec(
        select(TaxBenefitModelVersion)
        .join(TaxBenefitModel, TaxBenefitModel.id == TaxBenefitModelVersion.model_id)
        .where(
            TaxBenefitModel.name == "policyengine-us",
            TaxBenefitModelVersion.version == POLICYENGINE_VERSION,
        )
    ).one()


def _service(
    session: Session, *, selected_catalogs: SelectedCatalogStore | None = None
) -> V2MetadataService:
    return V2MetadataService(
        MetadataDatabaseSession(session),
        running_policyengine_version=POLICYENGINE_VERSION,
        selected_catalogs=selected_catalogs,
    )


def test_resource_collection_uses_bounded_pagination_without_counting(
    catalog_session: Session,
) -> None:
    model_version = _us_model_version(catalog_session)
    catalog_session.add(
        Variable(
            id=uuid4(),
            tax_benefit_model_version_id=model_version.id,
            name="pension_income",
            label="Pension income",
            entity="person",
            description="Pension income before tax",
            data_type="float",
            possible_values=None,
            default_value=0,
            adds=None,
            subtracts=None,
        )
    )
    catalog_session.commit()
    statements: list[str] = []

    def record_statement(_connection, _cursor, statement, *_args) -> None:
        statements.append(statement.lower())

    bind = catalog_session.get_bind()
    event.listen(bind, "before_cursor_execute", record_statement)
    try:
        result = _service(catalog_session).list_variables("us", limit=1)
    finally:
        event.remove(bind, "before_cursor_execute", record_statement)

    assert [item.name for item in result.items] == ["employment_income"]
    assert result.policyengine_version == POLICYENGINE_VERSION
    assert result.offset == 0
    assert result.limit == 1
    assert result.has_more is True
    assert len(statements) == 2
    assert all("count(" not in statement for statement in statements)
    assert "limit ? offset ?" in statements[-1]


@pytest.mark.parametrize(
    ("offset", "limit"),
    [(-1, 100), (0, 0), (0, 501)],
)
def test_resource_collection_rejects_out_of_range_pages_before_querying(
    catalog_session: Session,
    offset: int,
    limit: int,
) -> None:
    statements: list[str] = []

    def record_statement(_connection, _cursor, statement, *_args) -> None:
        statements.append(statement)

    bind = catalog_session.get_bind()
    event.listen(bind, "before_cursor_execute", record_statement)
    try:
        with pytest.raises(InvalidMetadataPageError):
            _service(catalog_session).list_variables(
                "us",
                offset=offset,
                limit=limit,
            )
    finally:
        event.remove(bind, "before_cursor_execute", record_statement)

    assert statements == []


def test_parameter_collection_does_not_query_or_embed_values(
    catalog_session: Session,
) -> None:
    statements: list[str] = []

    def record_statement(_connection, _cursor, statement, *_args) -> None:
        statements.append(statement.lower())

    bind = catalog_session.get_bind()
    event.listen(bind, "before_cursor_execute", record_statement)
    try:
        result = _service(catalog_session).list_parameters("us")
    finally:
        event.remove(bind, "before_cursor_execute", record_statement)

    assert [item.name for item in result.items] == ["gov.example.rate"]
    assert "values" not in result.items[0].model_dump()
    assert len(statements) == 2
    assert all("parameter_values" not in statement for statement in statements)


def test_parameter_values_are_separate_canonical_resources(
    catalog_session: Session,
) -> None:
    model_version = _us_model_version(catalog_session)
    parameter = catalog_session.exec(
        select(Parameter).where(
            Parameter.tax_benefit_model_version_id == model_version.id,
            Parameter.name == "gov.example.rate",
        )
    ).one()
    catalog_session.add(
        ParameterValue(
            id=uuid4(),
            parameter_id=parameter.id,
            value_json=0.9,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            end_date=None,
            policy_id=uuid4(),
        )
    )
    catalog_session.commit()

    all_values = _service(catalog_session).list_parameter_values(
        "us",
        value_filter=ParameterValueFilter(parameter_id=parameter.id),
    )
    current_value = _service(catalog_session).list_parameter_values(
        "us",
        value_filter=ParameterValueFilter(
            parameter_id=parameter.id,
            current=True,
            now=datetime(2026, 6, 1, tzinfo=UTC),
        ),
    )

    assert [item.value for item in all_values.items] == [0.2, 0.1]
    assert [item.value for item in current_value.items] == [0.2]
    assert all(item.parameter_id == parameter.id for item in all_values.items)


@pytest.mark.parametrize(
    ("selected_time", "expected_value"),
    [
        (datetime(2025, 12, 31, tzinfo=UTC), 0.1),
        (datetime(2025, 12, 31, 23, 59, tzinfo=UTC), 0.1),
        (datetime(2026, 1, 1, tzinfo=UTC), 0.2),
    ],
)
def test_current_parameter_value_uses_inclusive_effective_dates(
    catalog_session: Session,
    selected_time: datetime,
    expected_value: float,
) -> None:
    result = _service(catalog_session).list_parameter_values(
        "us",
        value_filter=ParameterValueFilter(current=True, now=selected_time),
    )

    assert [item.value for item in result.items] == [expected_value]


def test_parameter_children_are_loaded_one_level_at_a_time(
    catalog_session: Session,
) -> None:
    model_version = _us_model_version(catalog_session)
    nested_node = ParameterNode(
        id=uuid4(),
        tax_benefit_model_version_id=model_version.id,
        name="gov.example.nested",
        label="Nested parameters",
        description=None,
    )
    nested_parameter = Parameter(
        id=uuid4(),
        tax_benefit_model_version_id=model_version.id,
        name="gov.example.nested.amount",
        label="Nested amount",
        description=None,
        data_type="float",
        unit="currency-USD",
    )
    catalog_session.add_all([nested_node, nested_parameter])
    catalog_session.commit()
    service = _service(catalog_session)

    root = service.list_parameter_children("us")
    government = service.list_parameter_children("us", parent_path="gov")
    example = service.list_parameter_children("us", parent_path="gov.example")
    nested = service.list_parameter_children(
        "us",
        parent_path="gov.example.nested",
    )

    assert [(item.path, item.type) for item in root.items] == [("gov", "node")]
    assert [(item.path, item.type) for item in government.items] == [
        ("gov.example", "node")
    ]
    assert [(item.path, item.type) for item in example.items] == [
        ("gov.example.nested", "node"),
        ("gov.example.rate", "parameter"),
    ]
    assert [(item.path, item.type) for item in nested.items] == [
        ("gov.example.nested.amount", "parameter")
    ]
    assert root.items[0].child_count == 1
    assert government.items[0].child_count == 2
    assert example.items[0].child_count == 1
    assert example.items[1].parameter is not None


def test_resource_filters_and_details_remain_inside_selected_catalog(
    catalog_session: Session,
) -> None:
    service = _service(catalog_session)
    variables = service.list_variables("us", search="employment")
    parameters = service.list_parameters(
        "us", parameter_filter=ParameterFilter(search="example rate")
    )
    states = service.list_regions("us", region_type="state")
    region = service.get_region_by_code("us", "state/ca")

    assert [item.name for item in variables.items] == ["employment_income"]
    assert [item.name for item in parameters.items] == ["gov.example.rate"]
    assert [item.code for item in states.items] == ["state/ca"]
    assert region.item.code == "state/ca"
    with pytest.raises(MetadataResourceNotFoundError):
        service.get_region("us", uuid4())


def test_all_resource_families_support_collection_and_detail_reads(
    catalog_session: Session,
) -> None:
    service = _service(catalog_session)
    selection = service.get_model_by_country("us")
    model = service.list_models("us").items[0]
    model_version = service.list_model_versions("us").items[0]
    variable = service.list_variables("us").items[0]
    parameter = service.list_parameters("us").items[0]
    value = service.list_parameter_values(
        "us", value_filter=ParameterValueFilter(parameter_id=parameter.id)
    ).items[0]
    dataset = service.list_datasets("us").items[0]
    region = service.list_regions("us").items[0]

    assert service.get_model("us", model.id).item == model
    assert service.get_model_version("us", model_version.id).item == model_version
    assert service.get_variable("us", variable.id).item == variable
    assert service.get_parameter("us", parameter.id).item == parameter
    assert service.get_parameter_value("us", value.id).item == value
    assert service.get_dataset("us", dataset.id).item == dataset
    assert service.get_region("us", region.id).item == region
    assert selection.model == model
    assert selection.model_version == model_version


def test_each_resource_result_identifies_an_exact_selected_version(
    catalog_session: Session,
) -> None:
    _add_country_version(
        catalog_session,
        policyengine_version="5.0.5",
        current_law_id=22,
        time_periods=[2041, 2040],
    )
    service = _service(catalog_session)

    default_variables = service.list_variables("us")
    selected_variables = service.list_variables("us", "5.0.5")
    selected_options = service.get_economy_options("us", "5.0.5")

    assert default_variables.policyengine_version == POLICYENGINE_VERSION
    assert selected_variables.policyengine_version == "5.0.5"
    assert selected_options.policyengine_version == "5.0.5"
    assert selected_options.current_law_id == 22
    assert [item.name for item in selected_options.time_period] == [2041, 2040]


def test_version_selection_rejects_invalid_absent_and_unsupported_requests(
    catalog_session: Session,
) -> None:
    service = _service(catalog_session)

    for invalid in ("", f" {POLICYENGINE_VERSION}", "not a version", "0.0.0"):
        with pytest.raises(InvalidPolicyEngineVersionError):
            service.list_variables("us", invalid)
    with pytest.raises(MetadataCatalogVersionNotFoundError):
        service.list_variables("us", "4.99.0")
    with pytest.raises(UnsupportedPreviewCountryError):
        service.list_variables("ca")
    with pytest.raises(MetadataCatalogUnavailableError):
        V2MetadataService(
            MetadataDatabaseSession(catalog_session),
            running_policyengine_version="4.99.0",
        ).list_variables("us")


def test_dataset_collection_excludes_outputs_and_storage_references(
    catalog_session: Session,
) -> None:
    model_version = _us_model_version(catalog_session)
    output_id = uuid4()
    catalog_session.add(
        Dataset(
            id=output_id,
            tax_benefit_model_version_id=model_version.id,
            name="simulation-output",
            description="Generated result",
            storage_path="private-output-reference",
            year=2026,
            is_output_dataset=True,
        )
    )
    catalog_session.commit()

    service = _service(catalog_session)
    result = service.list_datasets("us")

    assert "simulation-output" not in {dataset.name for dataset in result.items}
    with pytest.raises(MetadataResourceNotFoundError):
        service.get_dataset("us", output_id)


def test_economy_options_read_only_regions_and_the_national_dataset(
    catalog_session: Session,
) -> None:
    statements: list[str] = []

    def record_statement(_connection, _cursor, statement, *_args) -> None:
        statements.append(statement.lower())

    bind = catalog_session.get_bind()
    event.listen(bind, "before_cursor_execute", record_statement)
    try:
        result = _service(catalog_session).get_economy_options("us")
    finally:
        event.remove(bind, "before_cursor_execute", record_statement)

    assert len(statements) == 3
    assert all("variables" not in statement for statement in statements)
    assert all("parameters" not in statement for statement in statements)
    assert [dataset.label for dataset in result.datasets] == ["Microcosm"]


def test_economy_options_require_a_national_region_and_dataset(
    catalog_session: Session,
) -> None:
    national_region = catalog_session.exec(
        select(Region).where(Region.code == "us")
    ).one()
    catalog_session.delete(national_region)
    catalog_session.commit()

    with pytest.raises(MetadataCatalogUnavailableError, match="national v2 region"):
        _service(catalog_session).get_economy_options("us")


def _recorded_statements(session: Session, read):
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


def test_model_catalog_holds_only_the_small_parts_of_a_catalog_version(
    catalog_session: Session,
) -> None:
    result, statements = _recorded_statements(
        catalog_session, lambda: _service(catalog_session).get_model_catalog("us")
    )
    us_catalog = normalized_catalog().country("us")

    assert result.policyengine_version == POLICYENGINE_VERSION
    assert result.catalog_format == 2
    assert result.model.name == "policyengine-us"
    assert (
        result.model_version.current_law_id == us_catalog.model_version.current_law_id
    )
    assert result.entities == [
        MetadataEntity(key="person", plural="people", is_person=True),
        MetadataEntity(key="household", plural="households", is_person=False),
    ]
    assert result.basic_inputs == ["employment_income"]
    assert [region.code for region in result.regions] == sorted(
        region.code for region in us_catalog.regions
    )
    assert [dataset.name for dataset in result.datasets] == sorted(
        dataset.name for dataset in us_catalog.datasets
    )
    assert [option.name for option in result.economy_options.region] == [
        region.code for region in result.regions
    ]
    assert [option.name for option in result.economy_options.time_period] == list(
        us_catalog.model_version.metadata_time_periods
    )
    assert [option.label for option in result.economy_options.datasets] == ["Microcosm"]
    assert len(statements) == 3
    for table in ("variables", "parameters", "parameter_values", "parameter_nodes"):
        assert all(f"from {table}" not in statement for statement in statements)


def test_model_catalog_without_regions_offers_no_economy_calculation(
    catalog_session: Session,
) -> None:
    # A household-only country publishes no regions or datasets; its catalog
    # still serves entities and basic inputs, with empty economy choices.
    model_version = _us_model_version(catalog_session)
    for region in catalog_session.exec(
        select(Region).where(Region.tax_benefit_model_version_id == model_version.id)
    ).all():
        catalog_session.delete(region)
    catalog_session.flush()
    for dataset in catalog_session.exec(
        select(Dataset).where(Dataset.tax_benefit_model_version_id == model_version.id)
    ).all():
        catalog_session.delete(dataset)
    catalog_session.commit()

    result = _service(catalog_session).get_model_catalog("us")

    assert result.regions == []
    assert result.datasets == []
    assert result.economy_options.region == []
    assert result.economy_options.time_period == []
    assert result.economy_options.datasets == []
    assert result.basic_inputs == ["employment_income"]


def test_model_catalog_published_before_format_2_has_empty_new_fields(
    catalog_session: Session,
) -> None:
    model_version = _us_model_version(catalog_session)
    model_version.catalog_format = None
    model_version.entities = None
    model_version.basic_inputs = None
    catalog_session.add(model_version)
    catalog_session.commit()

    result = _service(catalog_session).get_model_catalog("us")

    assert result.catalog_format is None
    assert result.entities == []
    assert result.basic_inputs == []


def test_model_catalog_with_regions_requires_the_national_region(
    catalog_session: Session,
) -> None:
    national_region = catalog_session.exec(
        select(Region).where(Region.code == "us")
    ).one()
    catalog_session.delete(national_region)
    catalog_session.commit()

    with pytest.raises(MetadataCatalogUnavailableError, match="national v2 region"):
        _service(catalog_session).get_model_catalog("us")


def _add_variable_with_parameter_named_parts(session: Session) -> None:
    model_version = _us_model_version(session)
    parts = Parameter(
        id=uuid4(),
        tax_benefit_model_version_id=model_version.id,
        name="gov.example.parts",
        label="Income parts",
        description=None,
        data_type="list",
        unit=None,
        economy=False,
        household=True,
    )
    session.add(parts)
    session.add_all(
        [
            ParameterValue(
                id=uuid4(),
                parameter_id=parts.id,
                value_json=["employment_income", "pension_income"],
                start_date=datetime(2026, 1, 1, tzinfo=UTC),
                end_date=None,
            ),
            ParameterValue(
                id=uuid4(),
                parameter_id=parts.id,
                value_json=["employment_income"],
                start_date=datetime(2024, 1, 1, tzinfo=UTC),
                end_date=datetime(2025, 12, 31, tzinfo=UTC),
            ),
            ParameterValue(
                id=uuid4(),
                parameter_id=parts.id,
                value_json=["reform_only_income"],
                start_date=datetime(2027, 1, 1, tzinfo=UTC),
                end_date=None,
                policy_id=uuid4(),
            ),
        ]
    )
    session.add(
        Variable(
            id=uuid4(),
            tax_benefit_model_version_id=model_version.id,
            name="total_income",
            label="Total income",
            entity="person",
            description=None,
            data_type="float",
            possible_values=["LOW", "HIGH"],
            default_value=0,
            adds=["employment_income"],
            subtracts=None,
            is_input_variable=False,
            hidden_input=True,
            module_name="household.income.total_income",
            adds_parameter_path="gov.example.parts",
            subtracts_parameter_path="gov.example.unpublished_parts",
            enum_values=[
                {"value": "LOW", "label": "Low"},
                {"value": "HIGH", "label": 2},
            ],
        )
    )
    session.commit()


def test_catalog_variables_hold_every_variable_with_its_format_2_fields(
    catalog_session: Session,
) -> None:
    _add_variable_with_parameter_named_parts(catalog_session)

    result, statements = _recorded_statements(
        catalog_session,
        lambda: _service(catalog_session).get_catalog_variables("us"),
    )

    assert result.policyengine_version == POLICYENGINE_VERSION
    assert result.catalog_format == 2
    assert [variable.name for variable in result.variables] == [
        "employment_income",
        "total_income",
    ]
    employment_income, total_income = result.variables
    assert employment_income.is_input_variable is True
    assert employment_income.hidden_input is False
    assert employment_income.module_name == "household.income.employment_income"
    assert employment_income.adds_parameter_path is None
    assert total_income.hidden_input is True
    assert total_income.adds_parameter_path == "gov.example.parts"
    assert total_income.subtracts_parameter_path == "gov.example.unpublished_parts"
    assert total_income.enum_values == [
        MetadataEnumValue(value="LOW", label="Low"),
        MetadataEnumValue(value="HIGH", label=2),
    ]
    assert len(statements) == 3


def test_catalog_variables_carry_the_dated_values_of_parameter_named_parts(
    catalog_session: Session,
) -> None:
    _add_variable_with_parameter_named_parts(catalog_session)

    result = _service(catalog_session).get_catalog_variables("us")

    assert result.part_parameter_values == {
        "gov.example.parts": [
            MetadataDatedValue(
                start_date=datetime(2024, 1, 1, tzinfo=UTC),
                end_date=datetime(2025, 12, 31, tzinfo=UTC),
                value=["employment_income"],
            ),
            MetadataDatedValue(
                start_date=datetime(2026, 1, 1, tzinfo=UTC),
                end_date=None,
                value=["employment_income", "pension_income"],
            ),
        ],
        "gov.example.unpublished_parts": [],
    }


def test_catalog_variables_without_parameter_named_parts_read_no_values(
    catalog_session: Session,
) -> None:
    result, statements = _recorded_statements(
        catalog_session,
        lambda: _service(catalog_session).get_catalog_variables("uk"),
    )

    assert [variable.name for variable in result.variables] == ["employment_income"]
    assert result.part_parameter_values == {}
    assert len(statements) == 2
    assert all("parameter_values" not in statement for statement in statements)


def test_variable_pages_carry_the_format_2_fields(catalog_session: Session) -> None:
    variable = _service(catalog_session).list_variables("us").items[0]

    assert variable.is_input_variable is True
    assert variable.module_name == "household.income.employment_income"
    assert variable.enum_values is None


def _add_bracket_schedule(session: Session) -> None:
    model_version = _us_model_version(session)
    session.add_all(
        [
            ParameterNode(
                id=uuid4(),
                tax_benefit_model_version_id=model_version.id,
                name="gov.example.rates",
                label="Example rates",
                description=None,
            ),
            ParameterNode(
                id=uuid4(),
                tax_benefit_model_version_id=model_version.id,
                name="gov.example.rates[0]",
                label=None,
                description=None,
            ),
        ]
    )
    bracket_rate = Parameter(
        id=uuid4(),
        tax_benefit_model_version_id=model_version.id,
        name="gov.example.rates[0].rate",
        label="Rate",
        description=None,
        data_type="float",
        unit="/1",
        economy=True,
        household=True,
    )
    session.add(bracket_rate)
    session.add(
        ParameterValue(
            id=uuid4(),
            parameter_id=bracket_rate.id,
            value_json=0.2,
            start_date=datetime(2025, 1, 1, tzinfo=UTC),
            end_date=None,
        )
    )
    session.commit()


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("gov", []),
        ("gov.example.rate", ["gov", "gov.example"]),
        (
            "gov.example.rates[0].rate",
            ["gov", "gov.example", "gov.example.rates", "gov.example.rates[0]"],
        ),
        ("gov.example.rates[10]", ["gov", "gov.example", "gov.example.rates"]),
    ],
)
def test_ancestor_paths_treat_a_bracket_index_as_a_child(
    name: str, expected: list[str]
) -> None:
    assert ancestor_paths(name) == expected


def test_named_parameters_load_with_values_and_ancestor_labels_in_one_read(
    catalog_session: Session,
) -> None:
    _add_bracket_schedule(catalog_session)

    result, statements = _recorded_statements(
        catalog_session,
        lambda: _service(catalog_session).get_catalog_parameters(
            "us",
            names=["gov.example.rates[0].rate", "gov.example.rate", "gov.example.rate"],
        ),
    )

    assert result.policyengine_version == POLICYENGINE_VERSION
    assert result.catalog_format == 2
    assert [parameter.name for parameter in result.parameters] == [
        "gov.example.rate",
        "gov.example.rates[0].rate",
    ]
    example_rate, bracket_rate = result.parameters
    assert (example_rate.economy, example_rate.household) == (True, False)
    assert [value.value for value in example_rate.values] == [0.1, 0.2]
    assert example_rate.values[0].start_date == datetime(2025, 1, 1, tzinfo=UTC)
    assert example_rate.values[0].end_date == datetime(2025, 12, 31, tzinfo=UTC)
    assert [value.value for value in bracket_rate.values] == [0.2]
    assert result.node_labels == {
        "gov.example": "Example policy",
        "gov.example.rates": "Example rates",
        "gov.example.rates[0]": None,
    }
    assert result.missing_names == []
    assert len(statements) == 4


def test_named_parameters_list_names_the_version_lacks(
    catalog_session: Session,
) -> None:
    result = _service(catalog_session).get_catalog_parameters(
        "uk", names=["gov.example.rate", "gov.removed.amount"]
    )

    assert [parameter.name for parameter in result.parameters] == ["gov.example.rate"]
    assert result.missing_names == ["gov.removed.amount"]


def test_named_parameters_exclude_policy_and_dynamic_values(
    catalog_session: Session,
) -> None:
    model_version = _us_model_version(catalog_session)
    parameter = catalog_session.exec(
        select(Parameter).where(
            Parameter.tax_benefit_model_version_id == model_version.id,
            Parameter.name == "gov.example.rate",
        )
    ).one()
    catalog_session.add(
        ParameterValue(
            id=uuid4(),
            parameter_id=parameter.id,
            value_json=0.9,
            start_date=datetime(2027, 1, 1, tzinfo=UTC),
            end_date=None,
            policy_id=uuid4(),
        )
    )
    catalog_session.commit()

    result = _service(catalog_session).get_catalog_parameters(
        "us", names=["gov.example.rate"]
    )

    assert [value.value for value in result.parameters[0].values] == [0.1, 0.2]


def test_parameter_pages_and_values_can_be_narrowed_to_named_parameters(
    catalog_session: Session,
) -> None:
    _add_bracket_schedule(catalog_session)
    service = _service(catalog_session)

    parameters = service.list_parameters(
        "us",
        parameter_filter=ParameterFilter(
            names=("gov.example.rates[0].rate", "gov.removed.amount")
        ),
    )
    values = service.list_parameter_values(
        "us",
        value_filter=ParameterValueFilter(
            parameter_names=("gov.example.rate", "gov.example.rates[0].rate")
        ),
    )

    assert [parameter.name for parameter in parameters.items] == [
        "gov.example.rates[0].rate"
    ]
    assert parameters.items[0].economy is True
    assert sorted(value.value for value in values.items) == [0.1, 0.2, 0.2]


def test_a_kept_catalog_selection_saves_its_query_on_later_reads(
    catalog_session: Session,
) -> None:
    store = SelectedCatalogStore()

    first, first_statements = _recorded_statements(
        catalog_session,
        lambda: _service(catalog_session, selected_catalogs=store).list_parameters(
            "us"
        ),
    )
    second, second_statements = _recorded_statements(
        catalog_session,
        lambda: _service(catalog_session, selected_catalogs=store).list_parameters(
            "us"
        ),
    )

    assert second == first
    assert len(first_statements) == 2
    assert len(second_statements) == 1
    assert "tax_benefit_model_versions" not in second_statements[0]


def test_failed_catalog_selections_are_not_kept(catalog_session: Session) -> None:
    store = SelectedCatalogStore()
    service = _service(catalog_session, selected_catalogs=store)

    for _attempt in range(2):
        with pytest.raises(MetadataCatalogVersionNotFoundError):
            service.list_parameters("us", "9.9.9")
        with pytest.raises(UnsupportedPreviewCountryError):
            service.list_parameters("ca")
        with pytest.raises(InvalidPolicyEngineVersionError):
            service.list_parameters("us", "not a version")

    _add_country_version(
        catalog_session,
        policyengine_version="9.9.9",
        current_law_id=7,
        time_periods=[2027],
    )
    assert service.list_parameters("us", "9.9.9").policyengine_version == "9.9.9"


def test_each_country_and_version_keeps_its_own_selection(
    catalog_session: Session,
) -> None:
    store = SelectedCatalogStore()
    _add_country_version(
        catalog_session,
        policyengine_version="9.9.9",
        current_law_id=7,
        time_periods=[2027],
    )
    service = _service(catalog_session, selected_catalogs=store)

    running_us = service.get_model_by_country("us")
    named_us = service.get_model_by_country("us", "9.9.9")
    running_uk = service.get_model_by_country("uk")

    assert (running_us.policyengine_version, named_us.policyengine_version) == (
        POLICYENGINE_VERSION,
        "9.9.9",
    )
    assert named_us.model_version.current_law_id == 7
    assert running_uk.model.name == "policyengine-uk"
    assert service.get_model_by_country("us", "9.9.9") == named_us


def test_read_modules_import_no_policyengine_or_v1_metadata_source() -> None:
    project_package = Path(__file__).parents[3] / "policyengine_api"
    connector_directory = (
        project_package / "services" / "v2" / "metadata" / "database_connectors"
    )
    modules = (
        project_package / "data" / "v2" / "catalog" / "catalog_selection.py",
        connector_directory / "reads.py",
        connector_directory / "reads_datasets.py",
        connector_directory / "reads_parameter_nodes.py",
        connector_directory / "reads_parameter_tree.py",
        connector_directory / "reads_parameters.py",
        connector_directory / "reads_regions.py",
        connector_directory / "reads_variables.py",
    )
    imported = set()
    for module in modules:
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        imported.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )

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


def test_resource_entrypoints_are_defined_in_the_service_module() -> None:
    method_names = {
        "list_models",
        "get_model",
        "get_model_by_country",
        "list_model_versions",
        "get_model_version",
        "list_variables",
        "get_variable",
        "list_parameters",
        "get_parameter",
        "list_parameter_children",
        "list_parameter_values",
        "get_parameter_value",
        "list_datasets",
        "get_dataset",
        "list_regions",
        "get_region",
        "get_region_by_code",
        "get_economy_options",
        "get_model_catalog",
        "get_catalog_variables",
        "get_catalog_parameters",
    }

    for method_name in method_names:
        method = getattr(V2MetadataService, method_name)
        assert method.__module__.endswith(".services")

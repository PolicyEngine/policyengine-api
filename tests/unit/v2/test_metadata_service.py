"""Read-only service coverage for v2 metadata resources."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlmodel import Session, select

from policyengine_api.data.v2.catalog.catalog_selection import (
    InvalidPolicyEngineVersionError,
    MetadataCatalogUnavailableError,
    MetadataCatalogVersionNotFoundError,
    UnsupportedPreviewCountryError,
)
from policyengine_api.data.v2.models import (
    Dataset,
    Parameter,
    ParameterValue,
    Region,
    Variable,
)
from policyengine_api.services.v2.metadata.database_session import (
    MetadataDatabaseSession,
)
from policyengine_api.services.v2.metadata.selected_catalogs import (
    SelectedCatalogStore,
)
from policyengine_api.services.v2.metadata.services import V2MetadataService
from policyengine_api.services.v2.metadata.types import (
    CurrentLawValueRow,
    MetadataEntity,
    ParameterFilter,
    ParameterNodeLabelRow,
    ParameterValueFilter,
)
from policyengine_api.services.v2.metadata.validators import (
    InvalidMetadataPageError,
    MetadataResourceNotFoundError,
)
from tests.fixtures.v2_catalog import POLICYENGINE_VERSION, normalized_catalog
from tests.fixtures.v2_metadata_service_helpers import (
    add_country_version,
    catalog_service,
    recorded_statements,
    stored_model_version,
)

pytest_plugins = ("tests.fixtures.v2_metadata_service",)


def test_resource_collection_uses_bounded_pagination_without_counting(
    catalog_session: Session,
) -> None:
    model_version = stored_model_version(catalog_session, "policyengine-us")
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
        result = catalog_service(catalog_session).list_variables("us", limit=1)
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
            catalog_service(catalog_session).list_variables(
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
        result = catalog_service(catalog_session).list_parameters("us")
    finally:
        event.remove(bind, "before_cursor_execute", record_statement)

    assert [item.name for item in result.items] == ["gov.example.rate"]
    assert "values" not in result.items[0].model_dump()
    assert len(statements) == 2
    assert all("parameter_values" not in statement for statement in statements)


def test_parameter_values_are_separate_canonical_resources(
    catalog_session: Session,
) -> None:
    model_version = stored_model_version(catalog_session, "policyengine-us")
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

    all_values = catalog_service(catalog_session).list_parameter_values(
        "us",
        value_filter=ParameterValueFilter(parameter_id=parameter.id),
    )
    current_value = catalog_service(catalog_session).list_parameter_values(
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
    result = catalog_service(catalog_session).list_parameter_values(
        "us",
        value_filter=ParameterValueFilter(current=True, now=selected_time),
    )

    assert [item.value for item in result.items] == [expected_value]


def test_resource_filters_and_details_remain_inside_selected_catalog(
    catalog_session: Session,
) -> None:
    service = catalog_service(catalog_session)
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
    service = catalog_service(catalog_session)
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
    add_country_version(
        catalog_session,
        policyengine_version="5.0.5",
        current_law_id=22,
        time_periods=[2041, 2040],
    )
    service = catalog_service(catalog_session)

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
    service = catalog_service(catalog_session)

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
    model_version = stored_model_version(catalog_session, "policyengine-us")
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

    service = catalog_service(catalog_session)
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
        result = catalog_service(catalog_session).get_economy_options("us")
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
        catalog_service(catalog_session).get_economy_options("us")


def test_model_catalog_holds_only_the_small_parts_of_a_catalog_version(
    catalog_session: Session,
) -> None:
    result, statements = recorded_statements(
        catalog_session,
        lambda: catalog_service(catalog_session).get_model_catalog("us"),
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
    model_version = stored_model_version(catalog_session, "policyengine-us")
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

    result = catalog_service(catalog_session).get_model_catalog("us")

    assert result.regions == []
    assert result.datasets == []
    assert result.economy_options.region == []
    assert result.economy_options.time_period == []
    assert result.economy_options.datasets == []
    assert result.basic_inputs == ["employment_income"]


def test_model_catalog_published_before_format_2_has_empty_new_fields(
    catalog_session: Session,
) -> None:
    model_version = stored_model_version(catalog_session, "policyengine-us")
    model_version.catalog_format = None
    model_version.entities = None
    model_version.basic_inputs = None
    catalog_session.add(model_version)
    catalog_session.commit()

    result = catalog_service(catalog_session).get_model_catalog("us")

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
        catalog_service(catalog_session).get_model_catalog("us")


def test_a_kept_catalog_selection_saves_its_query_on_later_reads(
    catalog_session: Session,
) -> None:
    store = SelectedCatalogStore()

    first, first_statements = recorded_statements(
        catalog_session,
        lambda: catalog_service(
            catalog_session, selected_catalogs=store
        ).list_parameters("us"),
    )
    second, second_statements = recorded_statements(
        catalog_session,
        lambda: catalog_service(
            catalog_session, selected_catalogs=store
        ).list_parameters("us"),
    )

    assert second == first
    assert len(first_statements) == 2
    assert len(second_statements) == 1
    assert "tax_benefit_model_versions" not in second_statements[0]


def test_failed_catalog_selections_are_not_kept(catalog_session: Session) -> None:
    store = SelectedCatalogStore()
    service = catalog_service(catalog_session, selected_catalogs=store)

    for _attempt in range(2):
        with pytest.raises(MetadataCatalogVersionNotFoundError):
            service.list_parameters("us", "9.9.9")
        with pytest.raises(UnsupportedPreviewCountryError):
            service.list_parameters("ca")
        with pytest.raises(InvalidPolicyEngineVersionError):
            service.list_parameters("us", "not a version")

    add_country_version(
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
    add_country_version(
        catalog_session,
        policyengine_version="9.9.9",
        current_law_id=7,
        time_periods=[2027],
    )
    service = catalog_service(catalog_session, selected_catalogs=store)

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


def test_value_and_node_label_reads_return_typed_rows(
    catalog_session: Session,
) -> None:
    from policyengine_api.services.v2.metadata.database_connectors import (
        reads_parameter_nodes,
        reads_parameters,
    )

    model_version = stored_model_version(catalog_session, "policyengine-us")
    values = reads_parameters.read_current_law_values_by_parameter_name(
        catalog_session,
        model_version_id=model_version.id,
        parameter_names={"gov.example.rate"},
    )
    labels = reads_parameter_nodes.read_parameter_node_labels(
        catalog_session,
        model_version_id=model_version.id,
        node_names={"gov.example", "gov.absent"},
    )

    assert [type(row) for row in values] == [CurrentLawValueRow, CurrentLawValueRow]
    assert [(row.name, row.value_json) for row in values] == [
        ("gov.example.rate", 0.1),
        ("gov.example.rate", 0.2),
    ]
    assert labels == [ParameterNodeLabelRow(name="gov.example", label="Example policy")]


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

"""Service coverage for whole-version variables and parameters fetched by name."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlmodel import Session, select

from policyengine_api.data.v2.models import (
    Parameter,
    ParameterNode,
    ParameterValue,
    Variable,
)
from policyengine_api.services.v2.metadata.transformations import ancestor_paths
from policyengine_api.services.v2.metadata.types import (
    MetadataDatedValue,
    MetadataEnumValue,
    ParameterFilter,
    ParameterValueFilter,
)
from tests.fixtures.v2_catalog import POLICYENGINE_VERSION
from tests.fixtures.v2_metadata_service_helpers import (
    add_country_version,
    catalog_service,
    recorded_statements,
    stored_model_version,
)

pytest_plugins = ("tests.fixtures.v2_metadata_service",)


def _add_variable_with_parameter_named_parts(session: Session) -> None:
    model_version = stored_model_version(session, "policyengine-us")
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

    result, statements = recorded_statements(
        catalog_session,
        lambda: catalog_service(catalog_session).get_catalog_variables("us"),
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

    result = catalog_service(catalog_session).get_catalog_variables("us")

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
    result, statements = recorded_statements(
        catalog_session,
        lambda: catalog_service(catalog_session).get_catalog_variables("uk"),
    )

    assert [variable.name for variable in result.variables] == ["employment_income"]
    assert result.part_parameter_values == {}
    assert len(statements) == 2
    assert all("parameter_values" not in statement for statement in statements)


def test_variable_pages_carry_the_format_2_fields(catalog_session: Session) -> None:
    variable = catalog_service(catalog_session).list_variables("us").items[0]

    assert variable.is_input_variable is True
    assert variable.module_name == "household.income.employment_income"
    assert variable.enum_values is None


def _add_bracket_schedule(session: Session) -> None:
    model_version = stored_model_version(session, "policyengine-us")
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

    result, statements = recorded_statements(
        catalog_session,
        lambda: catalog_service(catalog_session).get_catalog_parameters(
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
    result = catalog_service(catalog_session).get_catalog_parameters(
        "uk", names=["gov.example.rate", "gov.removed.amount"]
    )

    assert [parameter.name for parameter in result.parameters] == ["gov.example.rate"]
    assert result.missing_names == ["gov.removed.amount"]


def test_named_parameters_exclude_policy_and_dynamic_values(
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
            start_date=datetime(2027, 1, 1, tzinfo=UTC),
            end_date=None,
            policy_id=uuid4(),
        )
    )
    catalog_session.commit()

    result = catalog_service(catalog_session).get_catalog_parameters(
        "us", names=["gov.example.rate"]
    )

    assert [value.value for value in result.parameters[0].values] == [0.1, 0.2]


def test_parameter_pages_and_values_can_be_narrowed_to_named_parameters(
    catalog_session: Session,
) -> None:
    _add_bracket_schedule(catalog_session)
    service = catalog_service(catalog_session)

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


def test_variables_carry_their_unit_and_definition_period(
    catalog_session: Session,
) -> None:
    uk_version = stored_model_version(catalog_session, "policyengine-uk")
    catalog_session.add_all(
        [
            Variable(
                id=uuid4(),
                tax_benefit_model_version_id=uk_version.id,
                name="universal_credit",
                entity="benunit",
                data_type="float",
                default_value=0,
                unit="currency-GBP",
                definition_period="month",
            ),
            # A variable published before catalog format 2 stored neither.
            Variable(
                id=uuid4(),
                tax_benefit_model_version_id=uk_version.id,
                name="age",
                entity="person",
                data_type="int",
                default_value=0,
            ),
        ]
    )
    catalog_session.commit()
    service = catalog_service(catalog_session)

    us_variables = service.get_catalog_variables("us").variables
    uk_variables = {
        variable.name: variable
        for variable in service.get_catalog_variables("uk").variables
    }
    us_page = service.list_variables("us").items

    assert [(item.unit, item.definition_period) for item in us_variables] == [
        ("currency-USD", "year")
    ]
    assert (us_page[0].unit, us_page[0].definition_period) == (
        "currency-USD",
        "year",
    )
    assert (
        uk_variables["universal_credit"].unit,
        uk_variables["universal_credit"].definition_period,
    ) == ("currency-GBP", "month")
    assert (uk_variables["age"].unit, uk_variables["age"].definition_period) == (
        None,
        None,
    )


@pytest.mark.parametrize(
    ("country_id", "version", "expected_catalog_format", "expected_fields"),
    [
        ("us", None, 2, {"employment_income": ("currency-USD", "year")}),
        (
            "uk",
            None,
            2,
            {
                "employment_income": ("currency-USD", "year"),
                "universal_credit": ("currency-GBP", "month"),
            },
        ),
        # A version published before catalog format 2 stored neither field.
        ("us", "9.9.9", None, {"employment_income": (None, None)}),
    ],
)
def test_both_variables_routes_serve_unit_and_definition_period(
    catalog_session: Session,
    country_id: str,
    version: str | None,
    expected_catalog_format: int | None,
    expected_fields: dict[str, tuple[str | None, str | None]],
) -> None:
    from policyengine_api.fastapi_routes.v2.metadata.response_cache import (
        MetadataResponseCache,
    )
    from tests.fixtures.v2_metadata_routes import metadata_route_client

    catalog_session.add(
        Variable(
            id=uuid4(),
            tax_benefit_model_version_id=stored_model_version(
                catalog_session, "policyengine-uk"
            ).id,
            name="universal_credit",
            entity="benunit",
            data_type="float",
            default_value=0,
            unit="currency-GBP",
            definition_period="month",
        )
    )
    catalog_session.commit()
    add_country_version(
        catalog_session,
        policyengine_version="9.9.9",
        current_law_id=7,
        time_periods=[2027],
    )
    earlier_version = stored_model_version(catalog_session, "policyengine-us", "9.9.9")
    earlier_version.catalog_format = None
    for variable in catalog_session.exec(
        select(Variable).where(
            Variable.tax_benefit_model_version_id == earlier_version.id
        )
    ).all():
        variable.unit = None
        variable.definition_period = None
    catalog_session.commit()
    client = metadata_route_client(
        lambda: catalog_service(catalog_session), response_cache=MetadataResponseCache()
    )
    query = f"country_id={country_id}" + (
        "" if version is None else f"&policyengine_version={version}"
    )

    whole_version_bodies = [
        client.get(f"/v2/model-catalog/variables?{query}").json()["result"]
        for _attempt in ("read", "stored")
    ]
    page = client.get(f"/v2/variables?{query}").json()["result"]

    for result in whole_version_bodies:
        assert result["catalog_format"] == expected_catalog_format
        served = {
            variable["name"]: (variable["unit"], variable["definition_period"])
            for variable in result["variables"]
        }
        assert served == expected_fields
    paged = {
        item["name"]: (item["unit"], item["definition_period"])
        for item in page["items"]
    }
    assert paged == expected_fields

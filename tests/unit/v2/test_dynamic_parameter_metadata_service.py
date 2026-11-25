"""The metadata service's reads of the dynamic parameter category (C1 · 51).

They read only ``dynamic_parameters`` and the current-law rows of
``dynamic_parameter_values``. The children route's tree is built on each
request with ``parameter_tree.build_parameter_tree``, the stored node labels
and the version's enum labels, and keeps the parameters whose ``economy`` or
``household`` flag is true when ``settable`` is asked for.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from policyengine_api.services.v2.metadata.dynamic_parameters.types import (
    DynamicParameterTreeLevel,
)
from sqlmodel import Session, col, select

from policyengine_api.data.v2.models import (
    Dynamic,
    DynamicParameter,
    DynamicParameterValue,
    Parameter,
    ParameterNode,
    ParameterValue,
    Variable,
)
from policyengine_api.services.v2.metadata.process_state import (
    SelectedCatalogStore,
)
from policyengine_api.services.v2.metadata.types import (
    ParameterFilter,
    ParameterValueFilter,
)
from policyengine_api.services.v2.metadata.validators import (
    CatalogValuesPrunedError,
    MetadataResourceNotFoundError,
)
from tests.fixtures.database_sessions import sqlite_v2_sessions
from tests.fixtures.v2_catalog import catalog_with_dynamic_parameters
from tests.fixtures.v2_metadata_service_helpers import (
    catalog_service,
    insert_country,
    recorded_statements,
    stored_model_version,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

US_ELASTICITY = "gov.simulation.labor_supply_responses.elasticities.income"
US_TAX_RATE_DELTA = "simulation.marginal_tax_rate_delta"


@pytest.fixture
def dynamic_catalog_session() -> Iterator[Session]:
    """Return a Session of a database holding both catalogs and their assumptions."""
    with sqlite_v2_sessions() as sessions:
        with sessions.begin() as session:
            for country in catalog_with_dynamic_parameters().countries:
                insert_country(session, country, include_model=True)
        with sessions(expire_on_commit=True) as session:
            yield session


def _us_version_id(session: Session):
    return stored_model_version(session, "policyengine-us").id


def _dynamic_parameter(session: Session, name: str) -> DynamicParameter:
    return session.exec(
        select(DynamicParameter).where(
            col(DynamicParameter.name) == name,
            col(DynamicParameter.tax_benefit_model_version_id)
            == _us_version_id(session),
        )
    ).one()


def _add_us_dynamic_parameter(
    session: Session,
    name: str,
    *,
    label: str | None = None,
    economy: bool | None = True,
    household: bool | None = True,
) -> DynamicParameter:
    parameter = DynamicParameter(
        name=name,
        label=label,
        economy=economy,
        household=household,
        tax_benefit_model_version_id=_us_version_id(session),
    )
    session.add(parameter)
    session.commit()
    return parameter


def _add_us_dynamic(session: Session) -> Dynamic:
    version = stored_model_version(session, "policyengine-us")
    dynamic = Dynamic(
        country_id="us",
        tax_benefit_model_id=version.model_id,
        tax_benefit_model_version_id=version.id,
        canonicalization_version=1,
        content_hash="d" * 64,
    )
    session.add(dynamic)
    session.commit()
    return dynamic


def _prune_us_version(session: Session) -> None:
    """Delete the US version's current-law values and mark it pruned."""
    version = stored_model_version(session, "policyengine-us")
    current_law_values = session.exec(
        select(DynamicParameterValue)
        .join(DynamicParameter)
        .where(
            col(DynamicParameter.tax_benefit_model_version_id) == version.id,
            col(DynamicParameterValue.dynamic_id).is_(None),
        )
    ).all()
    for value in current_law_values:
        session.delete(value)
    version.catalog_values_pruned_at = datetime(2026, 11, 1, tzinfo=UTC)
    session.add(version)
    session.commit()


def _children(session: Session, parent_path: str = "", *, settable: bool = False):
    return catalog_service(session).dynamic_parameters.list_dynamic_parameter_children(
        "us",
        level=DynamicParameterTreeLevel(parent_path=parent_path, settable=settable),
    )


def test_dynamic_parameters_are_listed_apart_from_policy_parameters(
    dynamic_catalog_session: Session,
) -> None:
    service = catalog_service(dynamic_catalog_session)

    dynamic_page = service.dynamic_parameters.list_dynamic_parameters("us")
    policy_page = service.list_parameters("us")

    assert [item.name for item in dynamic_page.items] == [
        US_ELASTICITY,
        US_TAX_RATE_DELTA,
    ]
    assert [item.name for item in policy_page.items] == ["gov.example.rate"]
    assert dynamic_page.policyengine_version == policy_page.policyengine_version
    assert not dynamic_page.has_more


def test_the_dynamic_parameter_listing_filters_by_name_and_search(
    dynamic_catalog_session: Session,
) -> None:
    reads = catalog_service(dynamic_catalog_session).dynamic_parameters

    named = reads.list_dynamic_parameters(
        "uk",
        parameter_filter=ParameterFilter(
            names=("gov.dynamic.obr_labour_supply_assumptions", "gov.example.rate")
        ),
    )
    searched = reads.list_dynamic_parameters(
        "us", parameter_filter=ParameterFilter(search="MARGINAL")
    )
    wildcard = reads.list_dynamic_parameters(
        "us", parameter_filter=ParameterFilter(search="%")
    )

    assert [item.name for item in named.items] == [
        "gov.dynamic.obr_labour_supply_assumptions"
    ]
    assert [item.name for item in searched.items] == [US_TAX_RATE_DELTA]
    assert wildcard.items == []


def test_the_dynamic_parameter_listing_is_paged(
    dynamic_catalog_session: Session,
) -> None:
    reads = catalog_service(dynamic_catalog_session).dynamic_parameters

    first = reads.list_dynamic_parameters("us", limit=1)
    second = reads.list_dynamic_parameters("us", offset=1, limit=1)

    assert [item.name for item in first.items] == [US_ELASTICITY]
    assert first.has_more
    assert [item.name for item in second.items] == [US_TAX_RATE_DELTA]
    assert not second.has_more


def test_a_dynamic_parameter_is_read_by_id_and_other_ids_are_absent(
    dynamic_catalog_session: Session,
) -> None:
    reads = catalog_service(dynamic_catalog_session).dynamic_parameters
    stored = _dynamic_parameter(dynamic_catalog_session, US_TAX_RATE_DELTA)
    policy_parameter = dynamic_catalog_session.exec(
        select(Parameter).where(col(Parameter.name) == "gov.example.rate")
    ).first()
    assert policy_parameter is not None

    detail = reads.get_dynamic_parameter("us", stored.id)

    assert detail.item.name == US_TAX_RATE_DELTA
    assert detail.item.economy is True
    assert detail.item.household is True
    with pytest.raises(MetadataResourceNotFoundError) as policy_error:
        reads.get_dynamic_parameter("us", policy_parameter.id)
    assert str(policy_error.value) == (
        f"dynamic parameter {policy_parameter.id} was not found"
    )
    with pytest.raises(MetadataResourceNotFoundError):
        # The parameter belongs to the US version, not the UK one.
        reads.get_dynamic_parameter("uk", stored.id)


def test_the_us_tree_has_gov_and_simulation_at_its_top_level(
    dynamic_catalog_session: Session,
) -> None:
    top_level = _children(dynamic_catalog_session)
    simulation = _children(dynamic_catalog_session, "simulation")

    assert [(child.path, child.label, child.type) for child in top_level.items] == [
        ("gov", "Gov", "node"),
        ("simulation", "Simulation settings", "node"),
    ]
    assert [child.child_count for child in top_level.items] == [1, 1]
    assert [(child.path, child.label, child.type) for child in simulation.items] == [
        (US_TAX_RATE_DELTA, "Marginal tax rate delta", "parameter")
    ]
    leaf = simulation.items[0]
    assert leaf.child_count is None
    listed = catalog_service(
        dynamic_catalog_session
    ).dynamic_parameters.list_dynamic_parameters(
        "us", parameter_filter=ParameterFilter(names=(US_TAX_RATE_DELTA,))
    )
    assert leaf.parameter == listed.items[0]


def test_the_dynamic_tree_holds_no_policy_node(
    dynamic_catalog_session: Session,
) -> None:
    gov = _children(dynamic_catalog_session, "gov")
    policy_node = _children(dynamic_catalog_session, "gov.example")

    assert [child.path for child in gov.items] == ["gov.simulation"]
    assert policy_node.items == []
    assert not policy_node.has_more


def test_the_settable_level_keeps_only_what_a_dynamic_may_set(
    dynamic_catalog_session: Session,
) -> None:
    _add_us_dynamic_parameter(
        dynamic_catalog_session,
        "simulation.hidden",
        label="Hidden setting",
        economy=False,
        household=False,
    )
    _add_us_dynamic_parameter(
        dynamic_catalog_session,
        "simulation.household_only",
        label="A household setting",
        economy=False,
        household=True,
    )

    every_child = _children(dynamic_catalog_session, "simulation")
    settable = _children(dynamic_catalog_session, "simulation", settable=True)
    top_level = _children(dynamic_catalog_session, settable=True)

    assert [child.path for child in every_child.items] == [
        "simulation.hidden",
        "simulation.household_only",
        US_TAX_RATE_DELTA,
    ]
    # Sorted by label: "A household setting", then "Marginal tax rate delta".
    assert [child.path for child in settable.items] == [
        "simulation.household_only",
        US_TAX_RATE_DELTA,
    ]
    assert {child.path: child.child_count for child in top_level.items} == {
        "gov": 1,
        "simulation": 2,
    }


def test_a_version_without_flags_has_no_settable_children(
    dynamic_catalog_session: Session,
) -> None:
    for name in (US_ELASTICITY, US_TAX_RATE_DELTA):
        parameter = _dynamic_parameter(dynamic_catalog_session, name)
        parameter.economy = None
        parameter.household = None
        dynamic_catalog_session.add(parameter)
    dynamic_catalog_session.commit()

    assert _children(dynamic_catalog_session, settable=True).items == []
    assert [child.path for child in _children(dynamic_catalog_session).items] == [
        "gov",
        "simulation",
    ]


def test_dynamic_tree_levels_are_paged(dynamic_catalog_session: Session) -> None:
    reads = catalog_service(dynamic_catalog_session).dynamic_parameters

    first = reads.list_dynamic_parameter_children("us", limit=1)
    second = reads.list_dynamic_parameter_children("us", offset=1, limit=1)

    assert [child.path for child in first.items] == ["gov"]
    assert first.has_more
    assert [child.path for child in second.items] == ["simulation"]
    assert not second.has_more


def test_the_dynamic_tree_labels_breakdowns_with_the_versions_enum_labels(
    dynamic_catalog_session: Session,
) -> None:
    breakdown = "gov.simulation.example_breakdown"
    dynamic_catalog_session.add(
        ParameterNode(
            name=breakdown,
            label="Example breakdown",
            tax_benefit_model_version_id=_us_version_id(dynamic_catalog_session),
        )
    )
    _add_us_dynamic_parameter(
        dynamic_catalog_session,
        f"{breakdown}.SINGLE",
        label="Example breakdown (Single filer)",
    )
    without_enum_labels = _children(dynamic_catalog_session, breakdown)
    dynamic_catalog_session.add(
        Variable(
            name="filing_status",
            entity="tax_unit",
            enum_values=[{"value": "SINGLE", "label": "Single filer"}],
            tax_benefit_model_version_id=_us_version_id(dynamic_catalog_session),
        )
    )
    dynamic_catalog_session.commit()

    with_enum_labels, statements = recorded_statements(
        dynamic_catalog_session,
        lambda: _children(dynamic_catalog_session, breakdown),
    )

    assert [child.label for child in without_enum_labels.items] == [
        "Example breakdown (Single filer)"
    ]
    assert [child.label for child in with_enum_labels.items] == ["SINGLE"]
    enum_reads = [
        statement for statement in statements if "from variables" in statement
    ]
    assert len(enum_reads) == 1
    # Only the enum values are read, not whole variable rows.
    assert enum_reads[0].startswith("select variables.enum_values")


def test_dynamic_values_are_current_law_only(
    dynamic_catalog_session: Session,
) -> None:
    elasticity = _dynamic_parameter(dynamic_catalog_session, US_ELASTICITY)
    dynamic = _add_us_dynamic(dynamic_catalog_session)
    dynamics_value = DynamicParameterValue(
        dynamic_parameter_id=elasticity.id,
        dynamic_id=dynamic.id,
        value_json=0.3,
        start_date=datetime(2025, 1, 1, tzinfo=UTC),
    )
    later_value = DynamicParameterValue(
        dynamic_parameter_id=elasticity.id,
        value_json=0.2,
        start_date=datetime(2027, 1, 1, tzinfo=UTC),
    )
    dynamic_catalog_session.add_all([dynamics_value, later_value])
    dynamic_catalog_session.commit()
    reads = catalog_service(dynamic_catalog_session).dynamic_parameters
    policy_value = dynamic_catalog_session.exec(select(ParameterValue)).first()
    assert policy_value is not None

    page = reads.list_dynamic_parameter_values("us")

    assert [(item.parameter_id, item.value) for item in page.items] == [
        (elasticity.id, 0.2),
        (elasticity.id, 0.1),
        (_dynamic_parameter(dynamic_catalog_session, US_TAX_RATE_DELTA).id, 1000),
    ]
    assert reads.get_dynamic_parameter_value("us", later_value.id).item.value == 0.2
    for absent_id in (dynamics_value.id, policy_value.id):
        with pytest.raises(MetadataResourceNotFoundError) as error:
            reads.get_dynamic_parameter_value("us", absent_id)
        assert str(error.value) == f"dynamic parameter value {absent_id} was not found"


def test_the_value_listing_filters_by_parameter_and_day(
    dynamic_catalog_session: Session,
) -> None:
    elasticity = _dynamic_parameter(dynamic_catalog_session, US_ELASTICITY)
    dynamic_catalog_session.add(
        DynamicParameterValue(
            dynamic_parameter_id=elasticity.id,
            value_json=0.2,
            start_date=datetime(2027, 1, 1, tzinfo=UTC),
        )
    )
    dynamic_catalog_session.commit()
    reads = catalog_service(dynamic_catalog_session).dynamic_parameters

    by_id = reads.list_dynamic_parameter_values(
        "us", value_filter=ParameterValueFilter(parameter_id=elasticity.id)
    )
    by_name = reads.list_dynamic_parameter_values(
        "us",
        value_filter=ParameterValueFilter(parameter_names=(US_TAX_RATE_DELTA,)),
    )
    current = reads.list_dynamic_parameter_values(
        "us",
        value_filter=ParameterValueFilter(
            current=True, now=datetime(2026, 6, 1, tzinfo=UTC)
        ),
    )

    assert [item.value for item in by_id.items] == [0.2, 0.1]
    assert [item.value for item in by_name.items] == [1000]
    # 2025's values have no end date, so they are in effect in 2026; 2027's
    # value isn't yet.
    assert [item.value for item in current.items] == [0.1, 1000]


def test_the_catalog_read_returns_the_whole_category_with_values_and_labels(
    dynamic_catalog_session: Session,
) -> None:
    reads = catalog_service(dynamic_catalog_session).dynamic_parameters

    result = reads.get_catalog_dynamic_parameters("us")

    assert result.catalog_format == 2
    assert [parameter.name for parameter in result.parameters] == [
        US_ELASTICITY,
        US_TAX_RATE_DELTA,
    ]
    assert [
        [(value.start_date, value.value) for value in parameter.values]
        for parameter in result.parameters
    ] == [
        [(datetime(2025, 1, 1, tzinfo=UTC), 0.1)],
        [(datetime(2025, 1, 1, tzinfo=UTC), 1000)],
    ]
    assert result.parameters[1].id == (
        _dynamic_parameter(dynamic_catalog_session, US_TAX_RATE_DELTA).id
    )
    assert result.node_labels == {
        "gov.simulation": "Simulation",
        "gov.simulation.labor_supply_responses": "Labor supply responses",
        "gov.simulation.labor_supply_responses.elasticities": "Elasticities",
        "simulation": "Simulation settings",
    }


def test_the_catalog_read_of_the_uk_holds_its_gov_dynamic_assumption(
    dynamic_catalog_session: Session,
) -> None:
    result = catalog_service(
        dynamic_catalog_session
    ).dynamic_parameters.get_catalog_dynamic_parameters("uk")

    assert [parameter.name for parameter in result.parameters] == [
        "gov.dynamic.obr_labour_supply_assumptions",
        "gov.simulation.labour_supply_responses.income_elasticity",
    ]
    assert result.parameters[0].values[0].value is True


def test_reads_of_pruned_data_answer_for_a_pruned_version(
    dynamic_catalog_session: Session,
) -> None:
    _prune_us_version(dynamic_catalog_session)
    reads = catalog_service(dynamic_catalog_session).dynamic_parameters

    for read in (
        lambda: reads.list_dynamic_parameter_values("us"),
        lambda: reads.get_dynamic_parameter_value("us", uuid4()),
        lambda: reads.list_dynamic_parameter_children("us"),
        lambda: reads.get_catalog_dynamic_parameters("us"),
    ):
        with pytest.raises(CatalogValuesPrunedError) as error:
            read()
        # The fixture's version is the running one, which answers 503.
        assert error.value.running_version
    # Parameter rows are never pruned.
    assert len(reads.list_dynamic_parameters("us").items) == 2


def test_a_selection_kept_from_before_pruning_reads_the_marker_again(
    dynamic_catalog_session: Session,
) -> None:
    selected_catalogs = SelectedCatalogStore()
    reads = catalog_service(
        dynamic_catalog_session, selected_catalogs=selected_catalogs
    ).dynamic_parameters
    assert reads.list_dynamic_parameter_values("us").items
    _prune_us_version(dynamic_catalog_session)

    with pytest.raises(CatalogValuesPrunedError):
        reads.list_dynamic_parameter_values("us")
    with pytest.raises(CatalogValuesPrunedError):
        reads.get_catalog_dynamic_parameters("us")

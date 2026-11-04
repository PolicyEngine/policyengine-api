"""Service coverage for the stored parameter tree, one level at a time."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlmodel import Session, select

from policyengine_api.data.v2.catalog.parameter_tree import (
    TreeNodeSource,
    TreeParameterSource,
    build_parameter_tree,
)
from policyengine_api.data.v2.models import (
    Parameter,
    ParameterNode,
    ParameterTreeChild,
)
from policyengine_api.services.v2.metadata.types import (
    ParameterFilter,
    ParameterTreeLevel,
)
from policyengine_api.services.v2.metadata.validators import (
    ParameterTreeUnavailableError,
)
from tests.fixtures.v2_catalog import POLICYENGINE_VERSION
from tests.fixtures.v2_metadata_service_helpers import (
    catalog_service,
    stored_model_version,
)

pytest_plugins = ("tests.fixtures.v2_metadata_service",)


def _write_parameter_tree(session: Session, model_version_id) -> None:
    """Write a version's tree from its stored rows, without enum labels."""
    nodes = session.exec(
        select(ParameterNode).where(
            ParameterNode.tax_benefit_model_version_id == model_version_id
        )
    ).all()
    parameters = session.exec(
        select(Parameter).where(
            Parameter.tax_benefit_model_version_id == model_version_id
        )
    ).all()
    rows = build_parameter_tree(
        nodes=[TreeNodeSource(name=node.name, label=node.label) for node in nodes],
        parameters=[
            TreeParameterSource(
                id=parameter.id,
                name=parameter.name,
                label=parameter.label,
                economy=parameter.economy,
                household=parameter.household,
            )
            for parameter in parameters
        ],
    )
    session.add_all(
        ParameterTreeChild(
            tax_benefit_model_version_id=model_version_id,
            parent_path=row.parent_path,
            path=row.path,
            position=row.position,
            label=row.label,
            child_type=row.child_type,
            child_count=row.child_count,
            reform_position=row.reform_position,
            reform_child_count=row.reform_child_count,
            parameter_id=row.parameter_id,
            economy=row.economy,
            household=row.household,
        )
        for row in rows
    )
    session.commit()


def _level(parent_path: str = "", *, reform_changeable: bool = False):
    return ParameterTreeLevel(
        parent_path=parent_path, reform_changeable=reform_changeable
    )


def test_parameter_children_are_loaded_one_level_at_a_time(
    catalog_session: Session,
) -> None:
    model_version = stored_model_version(catalog_session, "policyengine-us")
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
    _write_parameter_tree(catalog_session, model_version.id)
    service = catalog_service(catalog_session)

    root = service.list_parameter_children("us")
    government = service.list_parameter_children("us", level=_level("gov"))
    example = service.list_parameter_children("us", level=_level("gov.example"))
    nested = service.list_parameter_children(
        "us",
        level=_level("gov.example.nested"),
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


def _add_parameters(session: Session, model_version, parameters) -> None:
    session.add_all(
        Parameter(
            id=uuid4(),
            tax_benefit_model_version_id=model_version.id,
            name=name,
            label=label,
            description=None,
            data_type="float",
            unit="/1",
            economy=economy,
            household=household,
        )
        for name, label, economy, household in parameters
    )


RATES = "gov.example.rates"


def test_bracket_schedules_are_one_node_whose_children_are_their_brackets(
    catalog_session: Session,
) -> None:
    model_version = stored_model_version(catalog_session, "policyengine-us")
    catalog_session.add_all(
        [
            ParameterNode(
                id=uuid4(),
                tax_benefit_model_version_id=model_version.id,
                name=RATES,
                label="Example rates",
                description=None,
            ),
            ParameterNode(
                id=uuid4(),
                tax_benefit_model_version_id=model_version.id,
                name=f"{RATES}.main",
                label="Main rates",
                description=None,
            ),
        ]
    )
    _add_parameters(
        catalog_session,
        model_version,
        [
            (f"{RATES}.main[0].rate", "Basic rate", True, True),
            (f"{RATES}.main[0].threshold", "Basic threshold", True, True),
            (f"{RATES}.main[1].rate", "Higher rate", True, True),
            (f"{RATES}.main[1].threshold", "Higher threshold", True, True),
            (f"{RATES}.dividends[0].rate", None, True, True),
        ],
    )
    catalog_session.commit()
    _write_parameter_tree(catalog_session, model_version.id)
    service = catalog_service(catalog_session)

    rates = service.list_parameter_children("us", level=_level(RATES))
    schedule = service.list_parameter_children("us", level=_level(f"{RATES}.main"))
    bracket = service.list_parameter_children("us", level=_level(f"{RATES}.main[0]"))

    assert [
        (item.path, item.label, item.type, item.child_count) for item in rates.items
    ] == [
        (f"{RATES}.dividends", "Dividends", "node", 1),
        (f"{RATES}.main", "Main rates", "node", 2),
    ]
    assert [
        (item.path, item.label, item.type, item.child_count) for item in schedule.items
    ] == [
        (f"{RATES}.main[0]", "Bracket 1", "node", 2),
        (f"{RATES}.main[1]", "Bracket 2", "node", 2),
    ]
    assert [(item.path, item.label, item.type) for item in bracket.items] == [
        (f"{RATES}.main[0].rate", "Basic rate", "parameter"),
        (f"{RATES}.main[0].threshold", "Basic threshold", "parameter"),
    ]
    assert bracket.items[0].parameter is not None
    assert bracket.items[0].parameter.name == f"{RATES}.main[0].rate"
    assert bracket.items[0].child_count is None


def test_the_reform_changeable_level_lists_only_what_a_reform_can_change(
    catalog_session: Session,
) -> None:
    model_version = stored_model_version(catalog_session, "policyengine-us")
    _add_parameters(
        catalog_session,
        model_version,
        [
            ("gov.tax.zero_rate", "Zero rate", True, False),
            ("gov.tax.allowance", "Allowance", False, True),
            ("gov.tax.internal", "Internal", False, False),
            ("gov.abolitions.tax", "Abolish tax", True, True),
        ],
    )
    catalog_session.commit()
    _write_parameter_tree(catalog_session, model_version.id)
    service = catalog_service(catalog_session)

    full = service.list_parameter_children("us", level=_level("gov.tax"))
    changeable = service.list_parameter_children(
        "us", level=_level("gov.tax", reform_changeable=True)
    )
    government = service.list_parameter_children(
        "us", level=_level("gov", reform_changeable=True)
    )

    assert [item.path for item in full.items] == [
        "gov.tax.allowance",
        "gov.tax.internal",
        "gov.tax.zero_rate",
    ]
    assert [item.label for item in changeable.items] == ["Allowance", "Zero rate"]
    assert {item.path: item.child_count for item in government.items} == {
        "gov.example": 1,
        "gov.tax": 2,
    }


def test_parameter_tree_levels_are_paged(catalog_session: Session) -> None:
    model_version = stored_model_version(catalog_session, "policyengine-us")
    _add_parameters(
        catalog_session,
        model_version,
        [(f"gov.paged.item_{index}", None, True, True) for index in range(3)],
    )
    catalog_session.commit()
    _write_parameter_tree(catalog_session, model_version.id)
    service = catalog_service(catalog_session)

    first = service.list_parameter_children(
        "us", level=_level("gov.paged"), offset=0, limit=2
    )
    last = service.list_parameter_children(
        "us", level=_level("gov.paged"), offset=2, limit=2
    )

    assert [item.path for item in first.items] == [
        "gov.paged.item_0",
        "gov.paged.item_1",
    ]
    assert first.has_more is True
    assert [item.path for item in last.items] == ["gov.paged.item_2"]
    assert last.has_more is False


def test_the_reform_changeable_level_is_paged_in_label_order(
    catalog_session: Session,
) -> None:
    model_version = stored_model_version(catalog_session, "policyengine-us")
    _add_parameters(
        catalog_session,
        model_version,
        [
            ("gov.paged.c_item", "Cherry", True, False),
            ("gov.paged.a_item", "Banana", False, True),
            ("gov.paged.b_item", "Apple", True, True),
            ("gov.paged.d_item", "Date", False, False),
        ],
    )
    catalog_session.commit()
    _write_parameter_tree(catalog_session, model_version.id)
    service = catalog_service(catalog_session)
    level = _level("gov.paged", reform_changeable=True)

    first = service.list_parameter_children("us", level=level, offset=0, limit=2)
    last = service.list_parameter_children("us", level=level, offset=2, limit=2)

    assert [item.label for item in first.items] == ["Apple", "Banana"]
    assert first.has_more is True
    assert [item.label for item in last.items] == ["Cherry"]
    assert last.has_more is False


def test_an_unwritten_parameter_tree_is_reported_as_unavailable(
    catalog_session: Session,
) -> None:
    service = catalog_service(catalog_session)

    with pytest.raises(
        ParameterTreeUnavailableError,
        match=(
            f"catalog version {POLICYENGINE_VERSION} has no parameter tree: "
            "catalog publication writes trees only for the versions it publishes"
        ),
    ):
        service.list_parameter_children("us")


def test_an_unknown_parent_in_a_written_tree_has_no_children(
    catalog_session: Session,
) -> None:
    model_version = stored_model_version(catalog_session, "policyengine-us")
    _write_parameter_tree(catalog_session, model_version.id)

    result = catalog_service(catalog_session).list_parameter_children(
        "us", level=_level("gov.nowhere")
    )

    assert result.items == []
    assert result.has_more is False


def test_parameter_tree_leaves_carry_the_same_summary_as_parameter_pages(
    catalog_session: Session,
) -> None:
    _write_parameter_tree(
        catalog_session, stored_model_version(catalog_session, "policyengine-us").id
    )
    service = catalog_service(catalog_session)

    leaf = next(
        child
        for child in service.list_parameter_children(
            "us", level=_level("gov.example")
        ).items
        if child.type == "parameter"
    )
    page_item = service.list_parameters(
        "us", parameter_filter=ParameterFilter(names=("gov.example.rate",))
    ).items[0]

    assert leaf.parameter == page_item
    assert (leaf.parameter.economy, leaf.parameter.household) == (True, False)

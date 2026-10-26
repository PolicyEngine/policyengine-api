"""Each catalog version's parameter tree, derived as rows of direct children."""

from __future__ import annotations

from uuid import uuid4

from policyengine_api.data.v2.catalog.parameter_tree import (
    ParameterTreeChildRow,
    TreeNodeSource,
    TreeParameterSource,
    build_parameter_tree,
    generated_label,
    parent_path,
)


def _parameter(
    name: str,
    *,
    label: str | None = None,
    economy: bool | None = True,
    household: bool | None = True,
) -> TreeParameterSource:
    return TreeParameterSource(
        id=uuid4(),
        name=name,
        label=label,
        economy=economy,
        household=household,
    )


def _rows_by_path(
    rows: tuple[ParameterTreeChildRow, ...],
) -> dict[str, ParameterTreeChildRow]:
    paths = [row.path for row in rows]
    assert len(paths) == len(set(paths)), "each path appears once"
    return {row.path: row for row in rows}


def _children(
    rows: tuple[ParameterTreeChildRow, ...], parent: str
) -> list[ParameterTreeChildRow]:
    return sorted(
        (row for row in rows if row.parent_path == parent),
        key=lambda row: row.position,
    )


def _reform_children(
    rows: tuple[ParameterTreeChildRow, ...], parent: str
) -> list[ParameterTreeChildRow]:
    visible = [
        row for row in rows if row.parent_path == parent and row.reform_changeable
    ]
    positions = [row.reform_position for row in visible]
    assert None not in positions
    assert sorted(positions) == list(range(len(visible)))
    return sorted(visible, key=lambda row: row.reform_position or 0)


UK_RATES = "gov.hmrc.income_tax.rates"


def _uk_income_tax_tree() -> tuple[ParameterTreeChildRow, ...]:
    """UK income tax: a schedule with a stored node row and one without."""
    nodes = [
        TreeNodeSource(name="gov", label=None),
        TreeNodeSource(name="gov.hmrc", label="HMRC"),
        TreeNodeSource(name="gov.hmrc.income_tax", label="Income Tax"),
        TreeNodeSource(name=UK_RATES, label="Income Tax rates"),
        TreeNodeSource(name=f"{UK_RATES}.uk", label="Income Tax main rates"),
        TreeNodeSource(name=f"{UK_RATES}.property", label=None),
    ]
    parameters = [
        _parameter(f"{UK_RATES}.uk[0].rate", label="Basic rate"),
        _parameter(f"{UK_RATES}.uk[0].threshold", label="Basic rate threshold"),
        _parameter(f"{UK_RATES}.uk[1].rate", label="Higher rate"),
        _parameter(f"{UK_RATES}.uk[1].threshold", label="Higher rate threshold"),
        _parameter(f"{UK_RATES}.dividends[0].rate"),
        _parameter(f"{UK_RATES}.dividends[0].threshold"),
        _parameter(f"{UK_RATES}.property.allowance", label="Property allowance"),
    ]
    return build_parameter_tree(nodes=nodes, parameters=parameters)


def test_parent_path_treats_a_bracket_as_a_child_of_its_schedule() -> None:
    assert parent_path("gov") == ""
    assert parent_path("gov.hmrc") == "gov"
    assert parent_path(f"{UK_RATES}.uk") == UK_RATES
    assert parent_path(f"{UK_RATES}.uk[0]") == f"{UK_RATES}.uk"
    assert parent_path(f"{UK_RATES}.uk[0].rate") == f"{UK_RATES}.uk[0]"


def test_generated_labels_follow_the_last_part_of_the_name() -> None:
    assert generated_label(f"{UK_RATES}.dividends") == "Dividends"
    assert generated_label("gov.example.non_primary_residence") == (
        "Non primary residence"
    )
    assert generated_label(f"{UK_RATES}.uk[0].rate") == "Rate"


def test_uk_schedules_nest_their_brackets_under_one_node() -> None:
    rows = _uk_income_tax_tree()
    by_path = _rows_by_path(rows)

    rates_children = _children(rows, UK_RATES)
    assert [row.path for row in rates_children] == [
        f"{UK_RATES}.dividends",
        f"{UK_RATES}.property",
        f"{UK_RATES}.uk",
    ]
    assert all(row.child_type == "node" for row in rates_children)

    stored_schedule = by_path[f"{UK_RATES}.uk"]
    assert stored_schedule.label == "Income Tax main rates"
    assert stored_schedule.child_count == 2
    assert [row.path for row in _children(rows, f"{UK_RATES}.uk")] == [
        f"{UK_RATES}.uk[0]",
        f"{UK_RATES}.uk[1]",
    ]
    assert [row.label for row in _children(rows, f"{UK_RATES}.uk")] == [
        "Bracket 1",
        "Bracket 2",
    ]

    unstored_schedule = by_path[f"{UK_RATES}.dividends"]
    assert unstored_schedule.label == "Dividends"
    assert unstored_schedule.child_type == "node"
    assert unstored_schedule.child_count == 1

    first_bracket = by_path[f"{UK_RATES}.uk[0]"]
    assert first_bracket.child_type == "node"
    assert first_bracket.child_count == 2
    assert [
        (row.path, row.label, row.child_type)
        for row in _children(rows, f"{UK_RATES}.uk[0]")
    ] == [
        (f"{UK_RATES}.uk[0].rate", "Basic rate", "parameter"),
        (f"{UK_RATES}.uk[0].threshold", "Basic rate threshold", "parameter"),
    ]


def test_us_schedule_brackets_are_ordered_by_number_not_by_text() -> None:
    schedule = "gov.aca.age_curves.al"
    parameters = [
        _parameter(f"{schedule}[{index}].{part}")
        for index in (0, 1, 2, 10, 11)
        for part in ("amount", "threshold")
    ]
    nodes = [TreeNodeSource(name=schedule, label="ACA premium age curve factors - AL")]

    rows = build_parameter_tree(nodes=nodes, parameters=parameters)
    brackets = _children(rows, schedule)

    assert [row.path for row in brackets] == [
        f"{schedule}[0]",
        f"{schedule}[1]",
        f"{schedule}[2]",
        f"{schedule}[10]",
        f"{schedule}[11]",
    ]
    assert [row.label for row in brackets] == [
        "Bracket 1",
        "Bracket 2",
        "Bracket 3",
        "Bracket 11",
        "Bracket 12",
    ]
    assert [row.path for row in _reform_children(rows, schedule)] == [
        row.path for row in brackets
    ]
    assert _rows_by_path(rows)[schedule].label == "ACA premium age curve factors - AL"
    assert [row.path for row in _children(rows, "")] == ["gov"]
    assert [row.path for row in _children(rows, "gov")] == ["gov.aca"]


def test_a_bracket_keeps_its_bracket_label_over_a_stored_one() -> None:
    schedule = f"{UK_RATES}.uk"
    rows = build_parameter_tree(
        nodes=[TreeNodeSource(name=f"{schedule}[0]", label="First band")],
        parameters=[_parameter(f"{schedule}[0].rate")],
    )

    assert _rows_by_path(rows)[f"{schedule}[0]"].label == "Bracket 1"


def test_parameters_carry_their_ids_and_flags_and_nodes_their_counts() -> None:
    rate = _parameter("gov.example.rate", label="Example rate", household=False)
    rows = build_parameter_tree(
        nodes=[TreeNodeSource(name="gov.example", label="Example policy")],
        parameters=[rate],
    )
    by_path = _rows_by_path(rows)

    leaf = by_path["gov.example.rate"]
    assert leaf.child_type == "parameter"
    assert leaf.parameter_id == rate.id
    assert (leaf.economy, leaf.household) == (True, False)
    assert leaf.child_count is None
    assert leaf.reform_child_count is None
    node = by_path["gov.example"]
    assert node.parameter_id is None
    assert (node.economy, node.household) == (None, None)
    assert (node.child_count, node.reform_child_count) == (1, 1)


def test_a_stored_node_without_children_is_an_empty_node() -> None:
    rows = build_parameter_tree(
        nodes=[TreeNodeSource(name="gov.empty", label="Nothing here")],
        parameters=[_parameter("gov.example.rate")],
    )
    empty = _rows_by_path(rows)["gov.empty"]

    assert empty.child_type == "node"
    assert empty.child_count == 0
    assert empty.reform_child_count == 0
    assert empty.reform_changeable is False
    assert empty.reform_position is None


def test_the_reform_view_keeps_only_what_a_reform_can_change() -> None:
    parameters = [
        _parameter("gov.tax.rate", label="Tax rate", economy=True, household=False),
        _parameter("gov.tax.credit", label="Credit", economy=False, household=True),
        _parameter("gov.tax.hidden", label="Hidden", economy=False, household=False),
        _parameter("gov.unchangeable.only", economy=False, household=False),
        _parameter("gov.abolitions.income_tax", label="Abolish income tax"),
        _parameter("gov.contrib.taxsim.rate", label="TAXSIM rate"),
        _parameter("calibration.gov.target", label="Calibration target"),
    ]
    rows = build_parameter_tree(nodes=[], parameters=parameters)
    by_path = _rows_by_path(rows)

    assert [row.path for row in _reform_children(rows, "")] == ["gov"]
    assert [row.path for row in _reform_children(rows, "gov")] == ["gov.tax"]
    assert [row.path for row in _reform_children(rows, "gov.tax")] == [
        "gov.tax.credit",
        "gov.tax.rate",
    ]
    assert by_path["gov.tax"].child_count == 3
    assert by_path["gov.tax"].reform_child_count == 2
    assert by_path["gov"].child_count == 4
    assert by_path["gov"].reform_child_count == 1
    for path in (
        "gov.tax.hidden",
        "gov.unchangeable",
        "gov.abolitions",
        "gov.contrib",
        "calibration",
    ):
        assert by_path[path].reform_changeable is False
        assert by_path[path].reform_position is None


def test_the_reform_view_is_sorted_by_label_as_v3_shows_it() -> None:
    parameters = [
        _parameter("gov.b_first", label="zebra crossing"),
        _parameter("gov.a_second", label="Apple orchard"),
        _parameter("gov.c_third"),
        _parameter("gov.d_fourth", label="banana_split"),
    ]
    rows = build_parameter_tree(nodes=[], parameters=parameters)

    assert [row.path for row in _children(rows, "gov")] == [
        "gov.a_second",
        "gov.b_first",
        "gov.c_third",
        "gov.d_fourth",
    ]
    assert [row.label for row in _reform_children(rows, "gov")] == [
        "Apple orchard",
        "Banana split",
        "C third",
        "Zebra crossing",
    ]


def test_every_row_has_its_parent_and_counts_match_the_rows() -> None:
    rows = _uk_income_tax_tree()
    by_path = _rows_by_path(rows)

    for row in rows:
        if row.parent_path:
            assert row.parent_path in by_path
        children = [child for child in rows if child.parent_path == row.path]
        if row.child_type == "node":
            assert row.child_count == len(children)
            assert row.reform_child_count == sum(
                child.reform_changeable for child in children
            )
        else:
            assert children == []
    for parent in {row.parent_path for row in rows}:
        positions = [row.position for row in rows if row.parent_path == parent]
        assert sorted(positions) == list(range(len(positions)))


def test_stored_labels_take_the_form_v3_shows_in_both_views() -> None:
    rows = build_parameter_tree(
        nodes=[
            TreeNodeSource(
                name="gov.transport", label="assumed uncapped single bus fare"
            )
        ],
        parameters=[
            _parameter("gov.transport.fare", label="ACA rating area NY (Child_only)"),
        ],
    )
    by_path = _rows_by_path(rows)

    assert by_path["gov.transport"].label == "Assumed uncapped single bus fare"
    assert by_path["gov.transport.fare"].label == "ACA rating area NY (Child only)"
    assert by_path["gov.transport"].reform_changeable is True


def test_schedules_without_a_stored_label_get_one_from_their_name() -> None:
    rows = build_parameter_tree(
        nodes=[],
        parameters=[
            _parameter(f"{UK_RATES}.uk[0].rate"),
            _parameter("gov.aca.age_curves.al[0].amount"),
        ],
    )
    by_path = _rows_by_path(rows)

    assert by_path[f"{UK_RATES}.uk"].label == "Uk"
    assert by_path["gov.aca.age_curves.al"].label == "Al"
    assert by_path[f"{UK_RATES}.uk[0]"].label == "Bracket 1"


AGE_CURVE = "gov.aca.age_curves.al"
STANDARD_DEDUCTION = "gov.irs.deductions.standard.amount"
PY_SHAPED_PARAMETERS = (
    # Bracket parameters labelled as PolicyEngine.py generates them.
    (f"{AGE_CURVE}[0].amount", "ACA premium age curve factors - AL (tier 1 amount)"),
    (
        f"{AGE_CURVE}[0].threshold",
        "ACA premium age curve factors - AL (tier 1 threshold)",
    ),
    (f"{AGE_CURVE}[1].amount", "ACA premium age curve factors - AL (tier 2 amount)"),
    # Breakdown parameters labelled from their parent node's label.
    (f"{STANDARD_DEDUCTION}.SINGLE", "Standard deduction (Single)"),
    (f"{STANDARD_DEDUCTION}.JOINT", "Standard deduction (Joint)"),
)


def _py_shaped_tree(*, schedule_has_node_row: bool):
    nodes = [TreeNodeSource(name=STANDARD_DEDUCTION, label="Standard deduction")]
    if schedule_has_node_row:
        nodes.append(
            TreeNodeSource(name=AGE_CURVE, label="ACA premium age curve factors - AL")
        )
    return build_parameter_tree(
        nodes=nodes,
        parameters=[
            _parameter(name, label=label) for name, label in PY_SHAPED_PARAMETERS
        ],
    )


def test_a_tree_from_the_locked_policyengine_py_labels_its_schedule_by_name() -> None:
    """The locked PolicyEngine.py stores no node row for a bracket schedule."""
    rows = _py_shaped_tree(schedule_has_node_row=False)
    by_path = _rows_by_path(rows)

    assert by_path[AGE_CURVE].label == "Al"
    assert [(row.label, row.child_count) for row in _children(rows, AGE_CURVE)] == [
        ("Bracket 1", 2),
        ("Bracket 2", 1),
    ]
    assert [row.label for row in _children(rows, f"{AGE_CURVE}[0]")] == [
        "ACA premium age curve factors - AL (tier 1 amount)",
        "ACA premium age curve factors - AL (tier 1 threshold)",
    ]
    assert by_path[STANDARD_DEDUCTION].label == "Standard deduction"
    assert [row.label for row in _children(rows, STANDARD_DEDUCTION)] == [
        "Standard deduction (Joint)",
        "Standard deduction (Single)",
    ]


def test_a_tree_from_a_release_with_schedule_nodes_uses_the_schedule_label() -> None:
    """A PolicyEngine.py release that publishes schedules stores their label."""
    rows = _py_shaped_tree(schedule_has_node_row=True)

    assert _rows_by_path(rows)[AGE_CURVE].label == (
        "ACA premium age curve factors - AL"
    )
    assert [row.label for row in _children(rows, AGE_CURVE)] == [
        "Bracket 1",
        "Bracket 2",
    ]

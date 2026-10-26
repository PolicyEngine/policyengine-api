"""Each catalog version's parameter search file, built from stored rows."""

from __future__ import annotations

import gzip
import hashlib
import json
from datetime import date

import pytest

from policyengine_api.data.v2.catalog.parameter_search_file import (
    PARAMETER_SEARCH_FILE_FORMAT,
    EditabilityChange,
    ParameterSearchFileDocument,
    SearchParameterSource,
    build_parameter_search_file,
    encode_parameter_search_file,
    is_editable_value,
)
from policyengine_api.data.v2.catalog.parameter_tree import TreeNodeSource


def _parameter(
    name: str,
    *,
    label: str | None = None,
    unit: str | None = None,
    description: str | None = None,
    flags: tuple[bool | None, bool | None] = (True, True),
) -> SearchParameterSource:
    economy, household = flags
    return SearchParameterSource(
        name=name,
        label=label,
        unit=unit,
        description=description,
        economy=economy,
        household=household,
    )


def _always_editable(*names: str) -> list[EditabilityChange]:
    return [
        EditabilityChange(
            parameter_name=name, start_date=date(2020, 1, 1), editable=True
        )
        for name in names
    ]


def _file(
    parameters: list[SearchParameterSource],
    *,
    nodes: list[TreeNodeSource] | None = None,
    editability: list[EditabilityChange] | None = None,
) -> ParameterSearchFileDocument:
    return build_parameter_search_file(
        country_id="uk",
        policyengine_version="6.10.0",
        parameters=parameters,
        nodes=nodes or [],
        editability=(
            editability
            if editability is not None
            else _always_editable(*(parameter.name for parameter in parameters))
        ),
    )


def test_the_file_names_its_format_country_and_version() -> None:
    search_file = _file([])

    assert search_file["format"] == PARAMETER_SEARCH_FILE_FORMAT == 1
    assert search_file["country_id"] == "uk"
    assert search_file["policyengine_version"] == "6.10.0"
    assert search_file["parameters"] == []
    assert search_file["other_parameters"] == []
    assert search_file["nodes"] == []


def test_each_changeable_parameter_has_what_v3_search_indexes() -> None:
    search_file = _file(
        [
            _parameter(
                "gov.hmrc.income_tax.rates.uk[0].rate",
                label="Basic rate",
                unit="/1",
                description="Rate on income in the basic band.",
            ),
            _parameter("gov.dwp.benefit_cap.single.in_london", unit="currency-GBP"),
        ]
    )

    assert search_file["parameters"] == [
        {
            "path": "gov.dwp.benefit_cap.single.in_london",
            "label": None,
            "unit": "currency-GBP",
            "description": None,
            "editable": True,
        },
        {
            "path": "gov.hmrc.income_tax.rates.uk[0].rate",
            "label": "Basic rate",
            "unit": "/1",
            "description": "Rate on income in the basic band.",
            "editable": True,
        },
    ]


def test_parameters_a_reform_cannot_change_keep_only_their_labels() -> None:
    search_file = _file(
        [
            _parameter("gov.hmrc.vat.rate", label="VAT rate"),
            _parameter(
                "gov.economic_assumptions.cpi",
                label="Consumer price index",
                flags=(False, False),
            ),
            _parameter("gov.abolitions.income_tax", label="Abolish income tax"),
            _parameter("gov.irs.taxsim.version", label="TAXSIM version"),
            _parameter("calibration.uprating.factor", label="Uprating factor"),
        ]
    )

    assert [entry["path"] for entry in search_file["parameters"]] == [
        "gov.hmrc.vat.rate"
    ]
    assert search_file["other_parameters"] == [
        {"path": "gov.abolitions.income_tax", "label": "Abolish income tax"},
        {"path": "gov.economic_assumptions.cpi", "label": "Consumer price index"},
        {"path": "gov.irs.taxsim.version", "label": "TAXSIM version"},
    ]


def test_a_parameter_with_either_flag_set_is_changeable() -> None:
    search_file = _file(
        [
            _parameter("gov.a.economy_only", flags=(True, False)),
            _parameter("gov.a.household_only", flags=(False, True)),
        ]
    )

    assert [entry["path"] for entry in search_file["parameters"]] == [
        "gov.a.economy_only",
        "gov.a.household_only",
    ]


def test_a_parameter_without_flags_is_not_changeable() -> None:
    search_file = _file(
        [
            _parameter("gov.a.rate", flags=(None, None)),
            _parameter("gov.a.other", flags=(False, False)),
        ]
    )

    assert search_file["parameters"] == []
    assert [entry["path"] for entry in search_file["other_parameters"]] == [
        "gov.a.other",
        "gov.a.rate",
    ]


def test_nodes_carry_their_stored_labels_only() -> None:
    search_file = _file(
        [_parameter("gov.hmrc.income_tax.rates.uk[0].rate")],
        nodes=[
            TreeNodeSource(name="gov.hmrc", label="HMRC"),
            TreeNodeSource(name="gov.hmrc.income_tax", label="Income Tax"),
            TreeNodeSource(
                name="gov.hmrc.income_tax.rates.uk", label="Income Tax main rates"
            ),
            TreeNodeSource(name="gov.hmrc.income_tax.rates", label=None),
            TreeNodeSource(name="gov.hmrc.income_tax.rates.uk[0]", label=" "),
            TreeNodeSource(name="calibration", label="Calibration"),
        ],
    )

    assert search_file["nodes"] == [
        {"path": "gov.hmrc", "label": "HMRC"},
        {"path": "gov.hmrc.income_tax", "label": "Income Tax"},
        {"path": "gov.hmrc.income_tax.rates.uk", "label": "Income Tax main rates"},
    ]


def test_the_labelled_gov_node_itself_is_included() -> None:
    # v3's concept clusters pair each node's key with its label, so the root
    # node's "Government" label must be in the file, as v1's metadata has it.
    search_file = _file(
        [_parameter("gov.hmrc.vat.rate")],
        nodes=[
            TreeNodeSource(name="gov", label="Government"),
            TreeNodeSource(name="government_bonds", label="Bonds"),
        ],
    )

    assert search_file["nodes"] == [{"path": "gov", "label": "Government"}]


def test_a_value_that_is_not_a_number_or_switch_cannot_be_edited() -> None:
    search_file = _file(
        [
            _parameter("gov.a.programs"),
            _parameter("gov.a.no_values"),
            _parameter("gov.a.threshold"),
        ],
        editability=[
            EditabilityChange("gov.a.programs", date(2020, 1, 1), editable=False),
            EditabilityChange("gov.a.threshold", date(2020, 1, 1), editable=True),
        ],
    )

    editable = {entry["path"]: entry["editable"] for entry in search_file["parameters"]}
    assert editable == {
        "gov.a.no_values": False,
        "gov.a.programs": False,
        "gov.a.threshold": True,
    }
    assert all("editable_changes" not in entry for entry in search_file["parameters"])


def test_editability_that_changes_over_time_lists_the_dates_it_changes() -> None:
    # A bracket that stops applying has a null value from that date and may
    # return later, so whether its current value can be edited depends on the
    # day it is read; the file states it for every date instead.
    search_file = _file(
        [
            _parameter(
                "gov.hmrc.stamp_duty.residential.purchase.main.subsequent[1].rate"
            )
        ],
        editability=[
            EditabilityChange(
                "gov.hmrc.stamp_duty.residential.purchase.main.subsequent[1].rate",
                date(2003, 7, 10),
                editable=True,
            ),
            EditabilityChange(
                "gov.hmrc.stamp_duty.residential.purchase.main.subsequent[1].rate",
                date(2015, 2, 12),
                editable=True,
            ),
            EditabilityChange(
                "gov.hmrc.stamp_duty.residential.purchase.main.subsequent[1].rate",
                date(2020, 7, 8),
                editable=False,
            ),
            EditabilityChange(
                "gov.hmrc.stamp_duty.residential.purchase.main.subsequent[1].rate",
                date(2021, 3, 31),
                editable=True,
            ),
        ],
    )

    (entry,) = search_file["parameters"]
    assert entry["editable"] is True
    assert entry["editable_changes"] == [
        {"start_date": "2020-07-08", "editable": False},
        {"start_date": "2021-03-31", "editable": True},
    ]


def test_the_earliest_value_decides_editability_before_any_change() -> None:
    search_file = _file(
        [_parameter("gov.hmrc.income_tax.rates.scotland.rates[0].rate")],
        editability=[
            EditabilityChange(
                "gov.hmrc.income_tax.rates.scotland.rates[0].rate",
                date(2018, 4, 6),
                editable=True,
            ),
            EditabilityChange(
                "gov.hmrc.income_tax.rates.scotland.rates[0].rate",
                date(2015, 1, 1),
                editable=False,
            ),
        ],
    )

    (entry,) = search_file["parameters"]
    assert entry["editable"] is False
    assert entry["editable_changes"] == [{"start_date": "2018-04-06", "editable": True}]


def test_the_encoded_file_is_compressed_json_with_its_content_hash() -> None:
    search_file = _file(
        [_parameter("gov.hmrc.vat.rate", label="VAT rate", unit="/1")],
        nodes=[TreeNodeSource(name="gov.hmrc", label="HMRC")],
    )

    encoded = encode_parameter_search_file(search_file)

    content = gzip.decompress(encoded.compressed_content)
    assert json.loads(content) == search_file
    assert encoded.content_sha256 == hashlib.sha256(content).hexdigest()
    assert encoded.uncompressed_size == len(content)
    assert encoded.compressed_size == len(encoded.compressed_content)


def test_the_same_catalog_rows_always_encode_to_the_same_bytes() -> None:
    parameters = [
        _parameter("gov.b.rate", label="B"),
        _parameter("gov.a.rate", label="Ä rate"),
    ]
    first = encode_parameter_search_file(_file(parameters))
    second = encode_parameter_search_file(_file(list(reversed(parameters))))

    assert first.compressed_content == second.compressed_content
    assert first.content_sha256 == second.content_sha256
    assert "Ä rate" in gzip.decompress(first.compressed_content).decode("utf-8")


@pytest.mark.parametrize(
    ("value", "editable"),
    [
        (0.2, True),
        (0, True),
        (True, True),
        (False, True),
        ("Infinity", True),
        ("-Infinity", True),
        (None, False),
        (["employment_income"], False),
        ("SINGLE", False),
        ({"a": 1}, False),
    ],
)
def test_editable_values_follow_v3s_draft_editor(
    value: object, *, editable: bool
) -> None:
    # v3's isDraftableValue: a number, a yes/no switch, or "Infinity"/"-Infinity".
    assert is_editable_value(value) is editable

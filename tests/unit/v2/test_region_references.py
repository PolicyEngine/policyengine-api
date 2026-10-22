"""The checked-in region reference files and the rules their loader enforces."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import pytest

from policyengine_api.data.congressional_districts import (
    AT_LARGE_STATES,
    CONGRESSIONAL_DISTRICTS,
    STATE_CODE_TO_NAME,
    build_congressional_district_metadata,
)
from policyengine_api.data.v2.catalog.errors import CatalogExtractionError
from policyengine_api.data.v2.catalog.region_references import (
    REGION_REFERENCE_FIELDS,
    RegionReference,
    load_region_references,
    parse_region_references,
)

V1_DATA_DIRECTORY = Path(__file__).parents[3] / "policyengine_api" / "data"
NATION_BY_ONS_PREFIX = {
    "E": "country/england",
    "S": "country/scotland",
    "W": "country/wales",
    "N": "country/northern_ireland",
}
ENGLISH_ITL1_REGIONS = [
    "NORTH_EAST",
    "NORTH_WEST",
    "YORKSHIRE",
    "EAST_MIDLANDS",
    "WEST_MIDLANDS",
    "EAST_OF_ENGLAND",
    "LONDON",
    "SOUTH_EAST",
    "SOUTH_WEST",
]


def _by_code(references: tuple[RegionReference, ...]) -> dict[str, RegionReference]:
    return {reference.code: reference for reference in references}


def _v1_lookup_rows(filename: str) -> list[dict[str, str]]:
    with (V1_DATA_DIRECTORY / filename).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _row(code: str, region_type: str, **fields: str) -> dict[str, str]:
    """Return one reference-file row; unspecified columns are empty."""
    row = dict.fromkeys(REGION_REFERENCE_FIELDS, "")
    row.update(code=code, label=code.title(), region_type=region_type, v1_code=code)
    row.update(fields)
    return row


def _small_us_rows() -> list[dict[str, str]]:
    return [
        _row("us", "national"),
        _row("state/ca", "state", parent_code="us", filter_value="6"),
        _row(
            "congressional_district/CA-01",
            "congressional_district",
            parent_code="state/ca",
        ),
    ]


def test_each_country_lists_every_region_once_with_the_expected_counts() -> None:
    us = load_region_references("us")
    uk = load_region_references("uk")

    assert Counter(reference.region_type for reference in us) == {
        "national": 1,
        "state": 51,
        "congressional_district": 436,
        "place": 333,
    }
    assert Counter(reference.region_type for reference in uk) == {
        "national": 1,
        "country": 4,
        "constituency": 650,
        "local_authority": 360,
    }
    assert len(uk) == 1_015
    for references in (us, uk):
        codes = [reference.code for reference in references]
        v1_codes = [reference.v1_code for reference in references]
        assert len(set(codes)) == len(codes)
        assert len(set(v1_codes)) == len(v1_codes)


def test_national_regions_and_the_v1_identifiers_they_replace() -> None:
    us = _by_code(load_region_references("us"))
    uk = _by_code(load_region_references("uk"))

    assert us["us"].label == "United States"
    assert uk["uk"].label == "United Kingdom"
    assert us["us"].parent_code is None
    assert uk["uk"].parent_code is None
    assert uk["country/northern_ireland"].v1_code == "country/ni"
    assert uk["country/northern_ireland"].label == "Northern Ireland"
    assert "country/ni" not in uk
    assert uk["constituency/E14001063"].label == "Aldershot"
    assert uk["constituency/E14001063"].v1_code == "constituency/Aldershot"
    assert uk["local_authority/E07000110"].label == "Maidstone"
    assert uk["local_authority/E07000110"].v1_code == "local_authority/Maidstone"
    assert us["state/ca"].v1_code == "state/ca"
    assert us["congressional_district/CA-01"].v1_code == "congressional_district/CA-01"


def test_uk_constituencies_and_local_authorities_use_ons_codes_from_v1_lookups() -> (
    None
):
    uk = load_region_references("uk")
    for region_type, filename in (
        ("constituency", "constituencies_2024.csv"),
        ("local_authority", "local_authorities_2021.csv"),
    ):
        expected = {
            f"{region_type}/{row['code']}": (
                row["name"],
                f"{region_type}/{row['name']}",
                row["code"],
                NATION_BY_ONS_PREFIX[row["code"][0]],
            )
            for row in _v1_lookup_rows(filename)
        }
        actual = {
            reference.code: (
                reference.label,
                reference.v1_code,
                reference.filter_value,
                reference.parent_code,
            )
            for reference in uk
            if reference.region_type == region_type
        }
        assert actual == expected


def test_uk_nations_select_their_stored_regions() -> None:
    uk = _by_code(load_region_references("uk"))

    assert json.loads(uk["country/england"].filter_value or "") == (
        ENGLISH_ITL1_REGIONS
    )
    assert uk["country/scotland"].filter_value == "SCOTLAND"
    assert uk["country/wales"].filter_value == "WALES"
    assert uk["country/northern_ireland"].filter_value == "NORTHERN_IRELAND"
    assert all(uk[code].parent_code == "uk" for code in NATION_BY_ONS_PREFIX.values())


def test_us_states_and_districts_match_v1_and_select_by_fips_and_geoid() -> None:
    us = load_region_references("us")
    states = {
        reference.state_code: reference
        for reference in us
        if reference.region_type == "state"
    }
    districts = {
        reference.code: reference
        for reference in us
        if reference.region_type == "congressional_district"
    }

    assert {code: state.label for code, state in states.items()} == (STATE_CODE_TO_NAME)
    assert all(state.code == f"state/{code.lower()}" for code, state in states.items())
    assert all(state.parent_code == "us" for state in states.values())
    assert states["CA"].filter_value == "6"
    assert states["DC"].filter_value == "11"

    v1_districts = {
        entry["name"]: entry for entry in build_congressional_district_metadata()
    }
    assert set(districts) == set(v1_districts)
    for district in CONGRESSIONAL_DISTRICTS:
        code = f"congressional_district/{district.state_code}-{district.number:02d}"
        reference = districts[code]
        number = 0 if district.state_code in AT_LARGE_STATES else district.number
        state_fips = int(states[district.state_code].filter_value or "")
        assert reference.label == v1_districts[code]["label"]
        assert reference.parent_code == f"state/{district.state_code.lower()}"
        assert reference.state_code == district.state_code
        assert reference.state_name == STATE_CODE_TO_NAME[district.state_code]
        assert reference.filter_value == str(state_fips * 100 + number)
    assert districts["congressional_district/CA-01"].filter_value == "601"
    assert districts["congressional_district/AK-01"].filter_value == "200"
    assert districts["congressional_district/DC-01"].filter_value == "1100"


def test_us_places_are_listed_under_their_state_without_a_filter() -> None:
    places = [
        reference
        for reference in load_region_references("us")
        if reference.region_type == "place"
    ]

    assert places
    assert all(place.filter_value is None for place in places)
    assert all(
        place.parent_code == f"state/{(place.state_code or '').lower()}"
        for place in places
    )
    assert all(place.v1_code == place.code for place in places)


def test_parses_a_valid_minimal_file() -> None:
    references = parse_region_references("us", _small_us_rows())

    assert [reference.code for reference in references] == [
        "us",
        "state/ca",
        "congressional_district/CA-01",
    ]
    assert references[1] == RegionReference(
        code="state/ca",
        label="State/Ca",
        region_type="state",
        parent_code="us",
        state_code=None,
        state_name=None,
        filter_value="6",
        v1_code="state/ca",
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda rows: rows.append(_row("state/ca", "state", parent_code="us")),
            r"^us region reference file repeats region codes: \['state/ca'\]$",
        ),
        (
            lambda rows: rows[2].update(v1_code="state/ca"),
            r"^us region reference file repeats v1 identifiers: \['state/ca'\]$",
        ),
        (
            lambda rows: rows[2].update(parent_code="state/ny"),
            r"^region 'congressional_district/CA-01' names an unknown parent "
            r"'state/ny'$",
        ),
        (
            lambda rows: rows.pop(0),
            r"^us region reference file has no national region 'us'$",
        ),
        (
            lambda rows: rows[1].update(region_type="place"),
            r"^region 'state/ca' does not start with its type 'place/'$",
        ),
        (
            lambda rows: rows.append(_row("county/06037", "county", parent_code="us")),
            r"^region 'county/06037' has unsupported type 'county'$",
        ),
        (
            lambda rows: rows[1].update(parent_code="congressional_district/CA-01"),
            r"^region 'state/ca' has a parent cycle$",
        ),
        (
            lambda rows: rows[0].update(parent_code="state/ca"),
            r"^national region 'us' must have no parent$",
        ),
        (
            lambda rows: rows[1].update(parent_code=""),
            r"^region 'state/ca' has no parent$",
        ),
        (
            lambda rows: rows[1].update(filter_value="x" * 256),
            r"^region 'state/ca' filter_value exceeds 255 characters$",
        ),
        (
            lambda rows: rows[1].update(label=" California"),
            r"^region 'state/ca' label has surrounding whitespace$",
        ),
        (
            lambda rows: rows[1].update(label=""),
            r"^region 'state/ca' label must be a non-empty string$",
        ),
    ],
)
def test_rejects_an_inconsistent_reference_file(change, message: str) -> None:
    rows = _small_us_rows()
    change(rows)

    with pytest.raises(CatalogExtractionError, match=message):
        parse_region_references("us", rows)


def test_rejects_a_file_whose_columns_differ(tmp_path: Path) -> None:
    (tmp_path / "us.csv").write_text(
        "code,label,region_type\nus,United States,national\n", encoding="utf-8"
    )

    with pytest.raises(
        CatalogExtractionError,
        match=r"^us region reference file columns must be ",
    ):
        load_region_references("us", directory=tmp_path)


def test_rejects_a_country_without_a_reference_file(tmp_path: Path) -> None:
    with pytest.raises(
        CatalogExtractionError,
        match=r"^ca has no region reference file$",
    ):
        load_region_references("ca", directory=tmp_path)

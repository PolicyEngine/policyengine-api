"""The UK region check's lists stay in step with .py's UK region registry.

.py's registry builds its constituencies and local authorities from area
lists packaged with policyengine, and includes them only when the installed
bundle's regional_release_kind is local_area. The Public API checks UK
regions against its own copies of those lists, the ones its UK metadata
offers, so these tests compare the copies with the installed package's files.
"""

import csv
from importlib.metadata import distribution
from pathlib import Path
from unittest.mock import patch

import pytest

from policyengine_api.data import uk_regions

RELEASE_LOOKUP = "policyengine_api.data.uk_regions.get_bundle_data_release"
POLICYENGINE_AREA_LISTS = {
    "constituency": "constituencies_2024.csv",
    "local_authority": "local_authorities_2023.csv",
}
AREA_COUNTS = {"constituency": 650, "local_authority": 361}


def _installed_policyengine_area_list(region_type: str) -> list[tuple[str, str]]:
    """Read one of .py's packaged area lists without importing policyengine."""
    area_list_path = distribution("policyengine").locate_file(
        f"policyengine/data/uk_geography/{POLICYENGINE_AREA_LISTS[region_type]}"
    )
    with Path(str(area_list_path)).open(encoding="utf-8") as area_file:
        return [(row["code"], row["name"]) for row in csv.DictReader(area_file)]


@pytest.mark.parametrize("region_type", sorted(POLICYENGINE_AREA_LISTS))
def test_each_area_list_matches_the_installed_policyengine_list(region_type):
    public_api_areas = sorted(
        (area.code, area.name) for area in uk_regions.uk_areas(region_type)
    )

    assert public_api_areas == sorted(_installed_policyengine_area_list(region_type))
    assert len(public_api_areas) == AREA_COUNTS[region_type]


@pytest.mark.parametrize(
    "region",
    [
        "constituency/E14001063",
        "constituency/Clapham and Brixton Hill",
        "local_authority/E09000022",
        "local_authority/lambeth",
    ],
)
@pytest.mark.parametrize(
    ("release", "resolves"),
    [
        ({"regional_release_kind": "local_area"}, True),
        ({"regional_release_kind": "area_coded_national"}, False),
        ({}, False),
    ],
    ids=["local_area", "area_coded_national", "no release kind"],
)
def test_area_regions_resolve_only_for_a_local_area_release(region, release, resolves):
    with patch(RELEASE_LOOKUP, return_value=release):
        resolved = uk_regions.resolve_uk_region(region)

    assert (resolved is not None) is resolves


@pytest.mark.parametrize(
    "release",
    [{"regional_release_kind": "area_coded_national"}, {}],
    ids=["area_coded_national", "no release kind"],
)
def test_countries_resolve_whatever_the_release_kind(release):
    with patch(RELEASE_LOOKUP, return_value=release):
        resolved = [
            uk_regions.resolve_uk_region(region)
            for region in ("uk", "country/wales", "Northern Ireland")
        ]

    assert resolved == ["uk", "country/wales", "country/northern_ireland"]


def test_the_accepted_forms_list_area_regions_only_for_a_local_area_release():
    with patch(RELEASE_LOOKUP, return_value={"regional_release_kind": "local_area"}):
        with_areas = uk_regions.describe_accepted_uk_regions()
    with patch(RELEASE_LOOKUP, return_value={}):
        without_areas = uk_regions.describe_accepted_uk_regions()

    assert with_areas.endswith(
        "; constituency/<constituency name or GSS code>; "
        "local_authority/<local authority name or GSS code>"
    )
    assert "constituency/" not in without_areas
    assert "local_authority/" not in without_areas


def test_area_regions_resolve_to_their_gss_code():
    resolved = [
        uk_regions.resolve_uk_region(region)
        for region in (
            "constituency/Clapham and Brixton Hill",
            "constituency/e14001063",
            "local_authority/Lambeth",
            "local_authority/e09000022",
        )
    ]

    assert resolved == [
        "constituency/E14001175",
        "constituency/E14001063",
        "local_authority/E09000022",
        "local_authority/E09000022",
    ]

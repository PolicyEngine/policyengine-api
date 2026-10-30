"""Resolve UK economy regions the way the simulation service does.

The simulation service runs a UK region only if .py's UK region registry
holds it, after normalising the requested spelling. That registry holds the
UK, its four countries and, when the installed bundle's
``regional_release_kind`` is ``local_area``, the constituencies and local
authorities from the area lists packaged with policyengine.

This module checks a region against the Public API's own copies of those
lists, the ones its UK metadata offers, so the check and the metadata always
agree and no part of .py is imported. Tests keep the copies equal to .py's
packaged files and the countries equal to .py's registry.
"""

from __future__ import annotations

import csv
from functools import cache
from pathlib import Path
from typing import NamedTuple

from policyengine_api.constants import (
    UK_COUNTRY_REGIONS,
    UK_REGION_REGISTRY_CODES,
    get_bundle_data_release,
)

UK_NATIONAL_REGION = "uk"
UK_COUNTRY_REGION_TYPE = "country"
# The release kind for which .py's registry lists constituencies and local
# authorities.
LOCAL_AREA_RELEASE_KIND = "local_area"
# The region types matched by name as well as by GSS code, with the noun the
# accepted-forms message uses for each.
UK_AREA_REGION_NOUNS = {
    "constituency": "constituency",
    "local_authority": "local authority",
}
UK_AREA_LIST_PATHS = {
    "constituency": Path(__file__).parent / "constituencies_2024.csv",
    "local_authority": Path(__file__).parent / "local_authorities_2021.csv",
}


class UKArea(NamedTuple):
    """One constituency or local authority: its GSS code and its name."""

    code: str
    name: str


@cache
def uk_areas(region_type: str) -> tuple[UKArea, ...]:
    """Return the constituencies or local authorities, in file order.

    The UK metadata and the region check both read the lists here, once per
    process.
    """
    with UK_AREA_LIST_PATHS[region_type].open(encoding="utf-8") as area_file:
        return tuple(
            UKArea(code=row["code"], name=row["name"])
            for row in csv.DictReader(area_file)
        )


@cache
def _area_codes_by_spelling(region_type: str) -> dict[str, str]:
    """Map each area's GSS code and name, case-folded, to its region code."""
    codes_by_spelling: dict[str, str] = {}
    for area in uk_areas(region_type):
        region_code = f"{region_type}/{area.code}"
        codes_by_spelling.setdefault(area.code.casefold(), region_code)
        codes_by_spelling.setdefault(area.name.casefold(), region_code)
    return codes_by_spelling


def uk_country_codes() -> tuple[str, ...]:
    """Return the code the payload sends for each country the metadata offers."""
    return tuple(
        dict.fromkeys(
            UK_REGION_REGISTRY_CODES.get(name, name)
            for name, _label in UK_COUNTRY_REGIONS
        )
    )


def area_regions_resolve() -> bool:
    """Whether the installed bundle's release kind lets area regions resolve.

    .py's registry lists constituencies and local authorities only when the
    bundle manifest's ``regional_release_kind`` is ``local_area``.
    """
    release = get_bundle_data_release("uk")
    return release.get("regional_release_kind") == LOCAL_AREA_RELEASE_KIND


def normalise_uk_region(region: str) -> str:
    """Spell a requested UK region as the simulation service normalises it.

    A blank region is the UK. A value without a type becomes a country, in
    lower case with spaces as underscores. The type is lower-cased; a country
    is lower-cased with spaces as underscores, and a local authority is
    upper-cased.
    """
    requested = region.strip()
    if requested == "" or requested.lower() == UK_NATIONAL_REGION:
        return UK_NATIONAL_REGION
    if "/" not in requested:
        return f"{UK_COUNTRY_REGION_TYPE}/{requested.lower().replace(' ', '_')}"
    region_type, value = requested.split("/", maxsplit=1)
    region_type = region_type.lower()
    value = value.strip()
    if region_type == UK_COUNTRY_REGION_TYPE:
        value = value.lower().replace(" ", "_")
    elif region_type == "local_authority":
        value = value.upper()
    return f"{region_type}/{value}"


def resolve_uk_region(region: str) -> str | None:
    """Return the registry code the simulation service runs ``region`` as.

    Return None when .py's UK region registry has no such region. A
    constituency or local authority matches its GSS code or its name, ignoring
    case, as the simulation service matches them.
    """
    code = normalise_uk_region(region)
    if code == UK_NATIONAL_REGION:
        return code
    region_type, _, value = code.partition("/")
    if region_type in UK_AREA_REGION_NOUNS:
        if not area_regions_resolve():
            return None
        return _area_codes_by_spelling(region_type).get(value.casefold())
    return code if code in uk_country_codes() else None


def _list_alternatives(names: list[str]) -> str:
    """Join names as ``a, b or c``."""
    *leading_names, last_name = names
    if not leading_names:
        return last_name
    return f"{', '.join(leading_names)} or {last_name}"


def describe_accepted_uk_regions(*, country_aliases: tuple[str, ...] = ()) -> str:
    """List the forms of UK region the check accepts.

    ``country_aliases`` are other country names the Public API accepts and
    sends as a registry code.
    """
    countries = [*uk_country_codes(), *country_aliases]
    forms = [UK_NATIONAL_REGION, _list_alternatives(countries)]
    if area_regions_resolve():
        forms.extend(
            f"{region_type}/<{noun} name or GSS code>"
            for region_type, noun in UK_AREA_REGION_NOUNS.items()
        )
    return "; ".join(forms)

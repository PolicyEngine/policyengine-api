"""Resolve UK economy regions the way the simulation service does.

The simulation service runs a UK region only if .py's UK region registry
holds it, after normalising the requested spelling. This module applies the
same normalisation to the registry in the installed policyengine package, so
the Public API can refuse a region before it stores or submits anything.

The registry lists constituencies and local authorities only when the
installed bundle's ``regional_release_kind`` is ``local_area``, so which area
regions resolve follows the installed bundle.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from policyengine.core.region import RegionRegistry

UK_NATIONAL_REGION = "uk"
UK_COUNTRY_REGION_TYPE = "country"
# The region types matched by name as well as by GSS code, with the noun the
# accepted-forms message uses for each.
UK_AREA_REGION_NOUNS = {
    "constituency": "constituency",
    "local_authority": "local authority",
}


def load_uk_region_registry() -> RegionRegistry:
    """Return .py's UK region registry from the installed policyengine package.

    The package is imported on first use rather than at startup: importing it
    also loads .py's country models.
    """
    regions_module = importlib.import_module("policyengine.countries.uk.regions")
    registry: RegionRegistry = regions_module.uk_region_registry
    return registry


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
    registry = load_uk_region_registry()
    region_type, _, value = code.partition("/")
    if region_type in UK_AREA_REGION_NOUNS:
        requested = value.casefold()
        for area in registry.get_by_type(region_type):
            area_code = area.code.partition("/")[2]
            if requested in {area_code.casefold(), area.label.casefold()}:
                return area.code
        return None
    return code if code in registry else None


def _list_alternatives(names: list[str]) -> str:
    """Join names as ``a, b or c``."""
    *leading_names, last_name = names
    if not leading_names:
        return last_name
    return f"{', '.join(leading_names)} or {last_name}"


def describe_accepted_uk_regions(*, country_aliases: tuple[str, ...] = ()) -> str:
    """List the forms of UK region the installed registry resolves.

    ``country_aliases`` are other country names the Public API accepts and
    sends as a registry code.
    """
    registry = load_uk_region_registry()
    countries = [region.code for region in registry.get_by_type(UK_COUNTRY_REGION_TYPE)]
    forms = [UK_NATIONAL_REGION, _list_alternatives([*countries, *country_aliases])]
    forms.extend(
        f"{region_type}/<{noun} name or GSS code>"
        for region_type, noun in UK_AREA_REGION_NOUNS.items()
        if registry.get_by_type(region_type)
    )
    return "; ".join(forms)

"""The Public API's checked-in region reference files, one per country.

Each file lists every region of one country: its code, label, type, parent,
US state, the value that selects its households in its dataset, and the v1
identifier it replaces. Catalog publication reads regions from these files,
never from PolicyEngine.py's region registry.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from policyengine_api.data.v2.catalog.errors import CatalogExtractionError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

REGION_REFERENCE_DIRECTORY = Path(__file__).parent / "region_reference_files"
REGION_REFERENCE_FIELDS = (
    "code",
    "label",
    "region_type",
    "parent_code",
    "state_code",
    "state_name",
    "filter_value",
    "v1_code",
)
SUPPORTED_REGION_TYPES = frozenset(
    {
        "national",
        "country",
        "state",
        "congressional_district",
        "constituency",
        "local_authority",
        "city",
        "place",
    }
)
# The catalog's region columns hold at most these many characters.
MAX_REGION_CODE_LENGTH = 255
MAX_REGION_LABEL_LENGTH = 255
MAX_REGION_STATE_CODE_LENGTH = 16
MAX_REGION_STATE_NAME_LENGTH = 128
MAX_REGION_FILTER_VALUE_LENGTH = 255


@dataclass(frozen=True, slots=True)
class RegionReference:
    """One region as its country's reference file lists it.

    ``filter_value`` is the text that selects the region's households: a FIPS
    number or district GEOID for US states and districts, the stored region
    names of a UK nation, or the ONS code of a UK constituency or local
    authority (its row in the weight matrix). The national region and regions
    that cannot run yet have none. ``v1_code`` is the v1 region identifier this
    region replaces, if v1 had one.
    """

    code: str
    label: str
    region_type: str
    parent_code: str | None
    state_code: str | None
    state_name: str | None
    filter_value: str | None
    v1_code: str | None


def _text(
    row: Mapping[str, str | None],
    field: str,
    *,
    code: str,
    maximum: int,
    required: bool,
) -> str | None:
    value = row.get(field) or ""
    if value != value.strip():
        msg = f"region {code!r} {field} has surrounding whitespace"
        raise CatalogExtractionError(msg)
    if not value:
        if required:
            msg = f"region {code!r} {field} must be a non-empty string"
            raise CatalogExtractionError(msg)
        return None
    if len(value) > maximum:
        msg = f"region {code!r} {field} exceeds {maximum} characters"
        raise CatalogExtractionError(msg)
    return value


def _reference(country_id: str, row: Mapping[str, str | None]) -> RegionReference:
    code = row.get("code") or ""
    if not code or code != code.strip() or len(code) > MAX_REGION_CODE_LENGTH:
        msg = f"{country_id} region reference file has an invalid code {code!r}"
        raise CatalogExtractionError(msg)
    region_type = row.get("region_type") or ""
    if region_type not in SUPPORTED_REGION_TYPES:
        msg = f"region {code!r} has unsupported type {region_type!r}"
        raise CatalogExtractionError(msg)
    if region_type != "national" and not code.startswith(f"{region_type}/"):
        msg = f"region {code!r} does not start with its type {region_type + '/'!r}"
        raise CatalogExtractionError(msg)
    return RegionReference(
        code=code,
        label=_text(
            row, "label", code=code, maximum=MAX_REGION_LABEL_LENGTH, required=True
        )
        or "",
        region_type=region_type,
        parent_code=_text(
            row,
            "parent_code",
            code=code,
            maximum=MAX_REGION_CODE_LENGTH,
            required=False,
        ),
        state_code=_text(
            row,
            "state_code",
            code=code,
            maximum=MAX_REGION_STATE_CODE_LENGTH,
            required=False,
        ),
        state_name=_text(
            row,
            "state_name",
            code=code,
            maximum=MAX_REGION_STATE_NAME_LENGTH,
            required=False,
        ),
        filter_value=_text(
            row,
            "filter_value",
            code=code,
            maximum=MAX_REGION_FILTER_VALUE_LENGTH,
            required=False,
        ),
        v1_code=_text(
            row, "v1_code", code=code, maximum=MAX_REGION_CODE_LENGTH, required=False
        ),
    )


def _repeated(values: Iterable[str | None]) -> list[str]:
    return sorted(
        value
        for value, count in Counter(value for value in values if value).items()
        if count > 1
    )


def _check_parents_present(
    country_id: str,
    references: tuple[RegionReference, ...],
) -> None:
    """Require one parentless national region and a parent for every other region."""
    if not any(reference.code == country_id for reference in references):
        msg = (
            f"{country_id} region reference file has no national region {country_id!r}"
        )
        raise CatalogExtractionError(msg)
    for reference in references:
        if reference.region_type == "national":
            if reference.code != country_id:
                msg = f"national region {reference.code!r} must be named {country_id!r}"
                raise CatalogExtractionError(msg)
            if reference.parent_code is not None:
                msg = f"national region {reference.code!r} must have no parent"
                raise CatalogExtractionError(msg)
        elif reference.parent_code is None:
            msg = f"region {reference.code!r} has no parent"
            raise CatalogExtractionError(msg)


def _check_ancestry(
    country_id: str,
    references: tuple[RegionReference, ...],
) -> None:
    """Require every region's parents to exist and lead to the national region."""
    parents = {reference.code: reference.parent_code for reference in references}
    for reference in references:
        visited = {reference.code}
        child = reference.code
        ancestor = reference.parent_code
        while ancestor is not None and ancestor != country_id:
            if ancestor not in parents:
                raise CatalogExtractionError(
                    _unknown_ancestor_message(reference.code, child, ancestor)
                )
            if ancestor in visited:
                msg = f"region {reference.code!r} has a parent cycle"
                raise CatalogExtractionError(msg)
            visited.add(ancestor)
            child, ancestor = ancestor, parents[ancestor]


def _unknown_ancestor_message(code: str, child: str, ancestor: str) -> str:
    """Name the missing region and, if it is further up, the region it parents."""
    if child == code:
        return f"region {code!r} names an unknown parent {ancestor!r}"
    return (
        f"region {code!r} descends from {child!r}, whose parent {ancestor!r} is unknown"
    )


def parse_region_references(
    country_id: str,
    rows: Iterable[Mapping[str, str | None]],
) -> tuple[RegionReference, ...]:
    """Validate one country's reference rows and return them in file order.

    Codes and v1 identifiers must be unique, every region's code must start
    with its type, and every region must descend from the national region.
    """
    references = tuple(_reference(country_id, row) for row in rows)
    repeated_codes = _repeated(reference.code for reference in references)
    if repeated_codes:
        msg = (
            f"{country_id} region reference file repeats region codes: {repeated_codes}"
        )
        raise CatalogExtractionError(msg)
    repeated_v1_codes = _repeated(reference.v1_code for reference in references)
    if repeated_v1_codes:
        msg = (
            f"{country_id} region reference file repeats v1 identifiers: "
            f"{repeated_v1_codes}"
        )
        raise CatalogExtractionError(msg)
    _check_parents_present(country_id, references)
    _check_ancestry(country_id, references)
    return references


def load_region_references(
    country_id: str,
    *,
    directory: Path = REGION_REFERENCE_DIRECTORY,
) -> tuple[RegionReference, ...]:
    """Read and validate the checked-in reference file of one country."""
    path = directory / f"{country_id}.csv"
    if not path.is_file():
        msg = f"{country_id} has no region reference file"
        raise CatalogExtractionError(msg)
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != REGION_REFERENCE_FIELDS:
            msg = (
                f"{country_id} region reference file columns must be "
                f"{', '.join(REGION_REFERENCE_FIELDS)}"
            )
            raise CatalogExtractionError(msg)
        return parse_region_references(country_id, reader)

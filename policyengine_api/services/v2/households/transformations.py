"""Pure representation transformations for v2 household operations."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from policyengine_core.periods import (  # type: ignore[import-untyped]
    period as parse_policyengine_period,
)

from policyengine_api.services.v2.households.types import (
    CanonicalHouseholdContent,
    HouseholdCreationInput,
    HouseholdPage,
    HouseholdRead,
    LegacyHouseholdSnapshot,
)
from policyengine_api.services.v2.households.validators import (
    SUPPORTED_ENTITY_COLLECTIONS,
    LegacyHouseholdTranslationError,
    normalize_household_document,
)

if TYPE_CHECKING:
    from policyengine_api.data.v2.models import Household

HOUSEHOLD_CANONICALIZATION_VERSION = 1
LEGACY_HOUSEHOLD_FINGERPRINT_VERSION = 1
LEGACY_COLLECTION_NAMES = {
    "household": "households",
    "family": "families",
    "tax_unit": "tax_units",
    "spm_unit": "spm_units",
    "marital_unit": "marital_units",
    "benunit": "benunits",
}


def _canonical_number(value: float) -> str:
    number = Decimal(str(value))
    if number.is_zero():
        return "0"
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _canonical_json(
    value: Any,  # noqa: ANN401  # exact type() dispatch that mypy cannot narrow
) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) in {int, float}:
        return _canonical_number(value)
    if type(value) is str:
        return json.dumps(value, ensure_ascii=True, allow_nan=False)
    if type(value) is list:
        return "[" + ",".join(_canonical_json(item) for item in value) + "]"
    if type(value) is dict:
        members = (
            f"{json.dumps(key, ensure_ascii=True)}:{_canonical_json(value[key])}"
            for key in sorted(value)
        )
        return "{" + ",".join(members) + "}"
    msg = "canonical household content contains a non-JSON value"
    raise TypeError(msg)


def canonical_household_document(household_input: HouseholdCreationInput) -> bytes:
    """Serialize a household to the canonical bytes that its content hash covers.

    People and entity records are sorted by id and keys are sorted, so the same
    household always yields the same bytes regardless of input order.
    """
    content = dict(cast("dict[str, Any]", household_input.household_data))
    for collection, records in content.items():
        if collection in {
            "people",
            *SUPPORTED_ENTITY_COLLECTIONS[household_input.country_id],
        }:
            if not isinstance(records, list):
                msg = f"household {collection} must be a list"
                raise TypeError(msg)
            typed_records = cast("list[dict[str, Any]]", records)
            content[collection] = sorted(
                typed_records,
                key=lambda record: cast("str", record["id"]),
            )
    document = {
        "canonicalization_version": HOUSEHOLD_CANONICALIZATION_VERSION,
        "country_id": household_input.country_id,
        "default_year": household_input.default_year,
        "household_data": content,
    }
    return _canonical_json(document).encode("ascii")


def canonicalize_household(
    household_input: HouseholdCreationInput,
) -> CanonicalHouseholdContent:
    """Return the canonical bytes, SHA-256 hash and canonicalization version."""
    document = canonical_household_document(household_input)
    return CanonicalHouseholdContent(
        version=HOUSEHOLD_CANONICALIZATION_VERSION,
        document=document,
        content_hash=hashlib.sha256(document).hexdigest(),
    )


def stored_household_creation_input(household: Household) -> HouseholdCreationInput:
    """Rebuild a stored row's creation input so its canonical bytes can be compared."""
    return HouseholdCreationInput.model_validate(
        {
            "country_id": household.country_id,
            "default_year": household.default_year,
            "household_data": household.household_data,
        }
    )


def household_read(household: Household) -> HouseholdRead:
    """Convert a stored household row to the service's read model."""
    return HouseholdRead(
        id=household.id,
        country_id=household.country_id,
        default_year=household.default_year,
        household_data=dict(household.household_data),
        created_at=household.created_at,
        updated_at=household.updated_at,
    )


def household_page(rows: list[Household], *, offset: int, limit: int) -> HouseholdPage:
    """Build a page from up to ``limit + 1`` rows.

    The extra row is not returned; it only sets ``has_more``.
    """
    displayed = rows[:limit]
    return HouseholdPage(
        items=tuple(household_read(row) for row in displayed),
        offset=offset,
        limit=limit,
        has_more=len(rows) > limit,
    )


def _stable_ids(kind: str, source_names: list[str]) -> dict[str, str]:
    return {
        source_name: f"{kind}-{index + 1}"
        for index, source_name in enumerate(sorted(source_names))
    }


def _period_years(value: object) -> set[int] | None:
    if type(value) is not dict or not value:
        return None
    years: set[int] = set()
    for period_key in value:
        if not isinstance(period_key, str):
            return None
        if period_key.upper() == "ETERNITY":
            continue
        try:
            parsed = parse_policyengine_period(period_key)
        except ValueError:
            return None
        years.add(parsed.start.year)
        years.add(parsed.stop.year)
    return years


def _derive_default_year(values: list[object]) -> int | None:
    explicit_periods = [_period_years(value) for value in values]
    years = set().union(*(item or set() for item in explicit_periods))
    if len(years) == 1:
        return next(iter(years))
    if all(item is not None for item in explicit_periods):
        return None
    msg = (
        "legacy household has values without explicit periods and no "
        "unambiguous default year"
    )
    raise LegacyHouseholdTranslationError(msg)


class _LegacyTranslation:
    """What translating one v1 household builds up as its groups are read.

    Holds the people's stable ids, each person's group memberships so far, and
    every source value in reading order, from which the default year is derived.
    """

    def __init__(self, people_source: dict[str, Any]) -> None:
        """Start a translation of the named people in ``people_source``."""
        self.person_ids = _stable_ids("person", list(people_source))
        self.person_memberships: dict[str, dict[str, str]] = {
            name: {} for name in people_source
        }
        self.all_values: list[object] = []


def translate_legacy_household(
    snapshot: LegacyHouseholdSnapshot,
) -> HouseholdCreationInput:
    """Translate a v1 household document into normalized v2 household content.

    Named v1 people and groups get stable ids in name order, and group members
    become person memberships. The default year is derived from the value periods.
    Raise LegacyHouseholdTranslationError when the v1 document cannot be
    translated exactly.
    """
    source = snapshot.household_json
    if not isinstance(source, dict):
        msg = "legacy household_json must be an object"
        raise TypeError(msg)
    collections = SUPPORTED_ENTITY_COLLECTIONS[snapshot.country_id]
    _require_supported_legacy_collections(snapshot.country_id, source, collections)
    people_source = source.get("people", {})
    if type(people_source) is not dict:
        msg = "legacy people must be an object"
        raise LegacyHouseholdTranslationError(msg)
    translation = _LegacyTranslation(people_source)
    normalized_groups = {
        collection: _translate_legacy_groups(source, collection, translation)
        for collection in collections
    }
    people = _translate_legacy_people(people_source, translation)

    document: dict[str, Any] = {"people": people, **normalized_groups}
    if "spm" in source:
        document["spm"] = source["spm"]
    try:
        normalized = normalize_household_document(snapshot.country_id, document)
    except ValueError as error:
        raise LegacyHouseholdTranslationError(str(error)) from error
    return HouseholdCreationInput(
        country_id=snapshot.country_id,
        default_year=_derive_default_year(translation.all_values),
        household_data=normalized,
    )


def _require_supported_legacy_collections(
    country_id: str,
    source: dict[str, Any],
    collections: tuple[str, ...],
) -> None:
    """Reject a v1 document with collections the country does not support."""
    allowed_source = {
        "people",
        *(LEGACY_COLLECTION_NAMES[item] for item in collections),
    }
    if country_id == "us":
        allowed_source.add("spm")
    unsupported = sorted(set(source) - allowed_source)
    if unsupported:
        msg = f"legacy household contains unsupported collections: {unsupported}"
        raise LegacyHouseholdTranslationError(msg)


def _translate_legacy_groups(
    source: dict[str, Any],
    collection: str,
    translation: _LegacyTranslation,
) -> list[dict[str, Any]]:
    """Translate one v1 collection's named groups into v2 records, in name order."""
    source_name = LEGACY_COLLECTION_NAMES[collection]
    source_groups = source.get(source_name, {})
    if type(source_groups) is not dict:
        msg = f"legacy {source_name} must be an object"
        raise LegacyHouseholdTranslationError(msg)
    group_ids = _stable_ids(collection, list(source_groups))
    group_records: list[dict[str, Any]] = []
    for group_name in sorted(source_groups):
        group = source_groups[group_name]
        if type(group) is not dict:
            msg = f"legacy {source_name} records must be objects"
            raise LegacyHouseholdTranslationError(msg)
        values = _translate_legacy_group(
            group,
            collection=collection,
            group_id=group_ids[group_name],
            translation=translation,
        )
        group_records.append(
            {
                "id": group_ids[group_name],
                "source_name": group_name,
                "values": values,
            }
        )
    return group_records


def _translate_legacy_group(
    group: dict[str, Any],
    *,
    collection: str,
    group_id: str,
    translation: _LegacyTranslation,
) -> dict[str, Any]:
    """Return a v1 group's values, recording its members' memberships."""
    values: dict[str, Any] = {}
    for field, value in group.items():
        if field != "members":
            values[field] = value
            translation.all_values.append(value)
            continue
        _record_legacy_memberships(
            value,
            collection=collection,
            group_id=group_id,
            translation=translation,
        )
    return values


def _record_legacy_memberships(
    members: object,
    *,
    collection: str,
    group_id: str,
    translation: _LegacyTranslation,
) -> None:
    """Record that each named member belongs to ``group_id`` in ``collection``."""
    source_name = LEGACY_COLLECTION_NAMES[collection]
    if type(members) is not list or not all(
        isinstance(item, str) and item in translation.person_ids for item in members
    ):
        msg = f"legacy {source_name} members must reference named people"
        raise LegacyHouseholdTranslationError(msg)
    for raw_person_name in members:
        if not isinstance(raw_person_name, str):
            msg = f"legacy {source_name} member names must be strings"
            raise TypeError(msg)
        person_name = raw_person_name
        memberships = translation.person_memberships[person_name]
        previous = memberships.get(collection)
        if previous is not None and previous != group_id:
            msg = (
                f"legacy person {person_name!r} belongs to multiple "
                f"{source_name} records"
            )
            raise LegacyHouseholdTranslationError(msg)
        memberships[collection] = group_id


def _translate_legacy_people(
    people_source: dict[str, Any],
    translation: _LegacyTranslation,
) -> list[dict[str, Any]]:
    """Translate the named v1 people into v2 person records, in name order."""
    people: list[dict[str, Any]] = []
    for person_name in sorted(people_source):
        person_values = people_source[person_name]
        if type(person_values) is not dict:
            msg = "legacy person records must be objects"
            raise LegacyHouseholdTranslationError(msg)
        translation.all_values.extend(person_values.values())
        people.append(
            {
                "id": translation.person_ids[person_name],
                "source_name": person_name,
                "values": dict(person_values),
                "memberships": translation.person_memberships[person_name],
            }
        )
    return people


def legacy_household_fingerprint(snapshot: LegacyHouseholdSnapshot) -> str:
    """Return a v1 snapshot's SHA-256 fingerprint, which detects changed v1 content."""
    document = {
        "fingerprint_version": LEGACY_HOUSEHOLD_FINGERPRINT_VERSION,
        **snapshot.model_dump(mode="json"),
    }
    return hashlib.sha256(_canonical_json(document).encode("ascii")).hexdigest()

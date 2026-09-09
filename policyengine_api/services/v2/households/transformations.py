"""Pure representation transformations for v2 household operations."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from typing import Any, cast

from policyengine_core.periods import period as parse_policyengine_period  # type: ignore[import-untyped]

from policyengine_api.data.v2.models import Household
from policyengine_api.services.v2.households.types import (
    CanonicalHouseholdContent,
    HouseholdCreationInput,
    HouseholdPage,
    HouseholdRead,
    LegacyHouseholdSnapshot,
)
from policyengine_api.services.v2.households.validators import (
    LegacyHouseholdTranslationError,
    SUPPORTED_ENTITY_COLLECTIONS,
    normalize_household_document,
)


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


def _canonical_number(value: int | float) -> str:
    number = Decimal(str(value))
    if number.is_zero():
        return "0"
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _canonical_json(value: Any) -> str:
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
    raise TypeError("canonical household content contains a non-JSON value")


def canonical_household_document(household_input: HouseholdCreationInput) -> bytes:
    content = dict(cast(dict[str, Any], household_input.household_data))
    for collection, records in content.items():
        if collection in {
            "people",
            *SUPPORTED_ENTITY_COLLECTIONS[household_input.country_id],
        }:
            assert isinstance(records, list)
            typed_records = cast(list[dict[str, Any]], records)
            content[collection] = sorted(
                typed_records,
                key=lambda record: cast(str, record["id"]),
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
    document = canonical_household_document(household_input)
    return CanonicalHouseholdContent(
        version=HOUSEHOLD_CANONICALIZATION_VERSION,
        document=document,
        content_hash=hashlib.sha256(document).hexdigest(),
    )


def stored_household_creation_input(household: Household) -> HouseholdCreationInput:
    return HouseholdCreationInput.model_validate(
        {
            "country_id": household.country_id,
            "default_year": household.default_year,
            "household_data": household.household_data,
        }
    )


def household_read(household: Household) -> HouseholdRead:
    return HouseholdRead(
        id=household.id,
        country_id=household.country_id,
        default_year=household.default_year,
        household_data=dict(household.household_data),
        created_at=household.created_at,
        updated_at=household.updated_at,
    )


def household_page(rows: list[Household], *, offset: int, limit: int) -> HouseholdPage:
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
        except Exception:  # noqa: BLE001 - parser exposes several value errors
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
    raise LegacyHouseholdTranslationError(
        "legacy household has values without explicit periods and no "
        "unambiguous default year"
    )


def translate_legacy_household(
    snapshot: LegacyHouseholdSnapshot,
) -> HouseholdCreationInput:
    source = snapshot.household_json
    assert isinstance(source, dict)
    collections = SUPPORTED_ENTITY_COLLECTIONS[snapshot.country_id]
    allowed_source = {
        "people",
        *(LEGACY_COLLECTION_NAMES[item] for item in collections),
    }
    unsupported = sorted(set(source) - allowed_source)
    if unsupported:
        raise LegacyHouseholdTranslationError(
            f"legacy household contains unsupported collections: {unsupported}"
        )
    people_source = source.get("people", {})
    if type(people_source) is not dict:
        raise LegacyHouseholdTranslationError("legacy people must be an object")
    person_ids = _stable_ids("person", list(people_source))
    all_values: list[object] = []
    normalized_groups: dict[str, list[dict[str, Any]]] = {}
    person_memberships: dict[str, dict[str, str]] = {name: {} for name in people_source}

    for collection in collections:
        source_name = LEGACY_COLLECTION_NAMES[collection]
        source_groups = source.get(source_name, {})
        if type(source_groups) is not dict:
            raise LegacyHouseholdTranslationError(
                f"legacy {source_name} must be an object"
            )
        group_ids = _stable_ids(collection, list(source_groups))
        group_records: list[dict[str, Any]] = []
        for group_name in sorted(source_groups):
            group = source_groups[group_name]
            if type(group) is not dict:
                raise LegacyHouseholdTranslationError(
                    f"legacy {source_name} records must be objects"
                )
            values: dict[str, Any] = {}
            for field, value in group.items():
                if field != "members":
                    values[field] = value
                    all_values.append(value)
                    continue
                if type(value) is not list or not all(
                    isinstance(item, str) and item in person_ids for item in value
                ):
                    raise LegacyHouseholdTranslationError(
                        f"legacy {source_name} members must reference named people"
                    )
                for raw_person_name in value:
                    assert isinstance(raw_person_name, str)
                    person_name = raw_person_name
                    memberships = person_memberships[person_name]
                    previous = memberships.get(collection)
                    if previous is not None and previous != group_ids[group_name]:
                        raise LegacyHouseholdTranslationError(
                            f"legacy person {person_name!r} belongs to multiple "
                            f"{source_name} records"
                        )
                    memberships[collection] = group_ids[group_name]
            group_records.append(
                {
                    "id": group_ids[group_name],
                    "source_name": group_name,
                    "values": values,
                }
            )
        normalized_groups[collection] = group_records

    people: list[dict[str, Any]] = []
    for person_name in sorted(people_source):
        person_values = people_source[person_name]
        if type(person_values) is not dict:
            raise LegacyHouseholdTranslationError(
                "legacy person records must be objects"
            )
        all_values.extend(person_values.values())
        people.append(
            {
                "id": person_ids[person_name],
                "source_name": person_name,
                "values": dict(person_values),
                "memberships": person_memberships[person_name],
            }
        )

    document = {"people": people, **normalized_groups}
    try:
        normalized = normalize_household_document(snapshot.country_id, document)
    except ValueError as error:
        raise LegacyHouseholdTranslationError(str(error)) from error
    return HouseholdCreationInput(
        country_id=snapshot.country_id,
        default_year=_derive_default_year(all_values),
        household_data=normalized,
    )


def legacy_household_fingerprint(snapshot: LegacyHouseholdSnapshot) -> str:
    document = {
        "fingerprint_version": LEGACY_HOUSEHOLD_FINGERPRINT_VERSION,
        **snapshot.model_dump(mode="json"),
    }
    return hashlib.sha256(_canonical_json(document).encode("ascii")).hexdigest()

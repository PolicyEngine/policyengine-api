"""Database-independent validation for v2 household operations."""

from __future__ import annotations

import math
from typing import Any
from uuid import UUID

from policyengine_api.data.v2.models import LegacyHouseholdMapping


MAXIMUM_HOUSEHOLD_ENTITIES = 1_000
MAXIMUM_HOUSEHOLD_RECORD_VALUES = 500
MAXIMUM_JSON_NESTING = 100
SUPPORTED_ENTITY_COLLECTIONS = {
    "us": ("household", "family", "tax_unit", "spm_unit", "marital_unit"),
    "uk": ("household", "benunit"),
}


class HouseholdValidationError(ValueError):
    """Raised when a household document violates its structural contract."""


class HouseholdNotFoundError(LookupError):
    """Raised when a household UUID is absent from the selected country."""


class HouseholdCreationIntegrityError(RuntimeError):
    """Raised when stored content cannot support safe deduplication."""


class HouseholdContentHashCollisionError(HouseholdCreationIntegrityError):
    """Raised when one version and digest identify different canonical bytes."""


class LegacyHouseholdMappingIntegrityError(RuntimeError):
    """Raised when one immutable v1 identity maps inconsistently."""


class LegacyHouseholdTranslationError(ValueError):
    """Raised when committed v1 household data cannot be translated exactly."""


def require_json_value(
    value: Any,
    *,
    depth: int = 0,
    containers: frozenset[int] = frozenset(),
) -> Any:
    """Reject values that are not standards-compliant JSON."""

    if depth > MAXIMUM_JSON_NESTING:
        raise ValueError("JSON values must not exceed 100 nested containers")
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    if type(value) not in {list, dict}:
        raise ValueError("value must contain only standards-compliant JSON types")
    identity = id(value)
    if identity in containers:
        raise ValueError("JSON values must not contain reference cycles")
    nested_containers = containers | {identity}
    if type(value) is list:
        for item in value:
            require_json_value(item, depth=depth + 1, containers=nested_containers)
        return value
    for key, item in value.items():
        if type(key) is not str:
            raise ValueError("JSON object keys must be strings")
        require_json_value(item, depth=depth + 1, containers=nested_containers)
    return value


def _require_identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise HouseholdValidationError(
            f"{field} must be a non-empty string of at most 255 characters"
        )
    return value


def _require_values(record: dict[str, Any], *, collection: str) -> None:
    values = record.get("values")
    if type(values) is not dict:
        raise HouseholdValidationError(f"{collection} record values must be an object")
    if len(values) > MAXIMUM_HOUSEHOLD_RECORD_VALUES:
        raise HouseholdValidationError(
            f"{collection} records must contain at most "
            f"{MAXIMUM_HOUSEHOLD_RECORD_VALUES} variable values"
        )
    require_json_value(values)


def _require_source_name(record: dict[str, Any], *, collection: str) -> None:
    source_name = record.get("source_name")
    if source_name is not None:
        _require_identifier(source_name, field=f"{collection} source_name")


def normalize_household_document(
    country_id: str,
    document: dict[str, Any],
) -> dict[str, Any]:
    """Validate and normalize one country-specific household document."""

    collections = SUPPORTED_ENTITY_COLLECTIONS.get(country_id)
    if collections is None:
        raise HouseholdValidationError(f"unsupported country_id {country_id!r}")
    if type(document) is not dict:
        raise HouseholdValidationError("household_data must be an object")
    allowed = {"people", *collections}
    unsupported = sorted(set(document) - allowed)
    if unsupported:
        raise HouseholdValidationError(
            f"household_data contains unsupported collections: {unsupported}"
        )
    if "people" not in document:
        raise HouseholdValidationError("household_data must contain people")

    normalized: dict[str, Any] = {}
    identifiers: dict[str, set[str]] = {}
    for collection in ("people", *collections):
        records = document.get(collection, [])
        if type(records) is not list:
            raise HouseholdValidationError(f"{collection} must be a list")
        if len(records) > MAXIMUM_HOUSEHOLD_ENTITIES:
            raise HouseholdValidationError(
                f"{collection} must contain at most {MAXIMUM_HOUSEHOLD_ENTITIES} records"
            )
        record_ids: set[str] = set()
        normalized_records: list[dict[str, Any]] = []
        expected_keys = (
            {"id", "source_name", "values", "memberships"}
            if collection == "people"
            else {"id", "source_name", "values"}
        )
        for record in records:
            if type(record) is not dict:
                raise HouseholdValidationError(f"{collection} records must be objects")
            unknown = sorted(set(record) - expected_keys)
            missing = sorted({"id", "values"} - set(record))
            if unknown or missing:
                raise HouseholdValidationError(
                    f"{collection} record fields are invalid: "
                    f"missing={missing}, unsupported={unknown}"
                )
            record_id = _require_identifier(record["id"], field=f"{collection} id")
            if record_id in record_ids:
                raise HouseholdValidationError(
                    f"{collection} contains duplicate id {record_id!r}"
                )
            record_ids.add(record_id)
            _require_source_name(record, collection=collection)
            _require_values(record, collection=collection)
            if collection == "people" and type(record.get("memberships")) is not dict:
                raise HouseholdValidationError(
                    "people record memberships must be an object"
                )
            normalized_records.append(dict(record))
        identifiers[collection] = record_ids
        normalized[collection] = normalized_records

    required_memberships = set(collections)
    for person in normalized["people"]:
        memberships = person["memberships"]
        assert isinstance(memberships, dict)
        if set(memberships) != required_memberships:
            raise HouseholdValidationError(
                "people record memberships must identify every country-supported "
                "entity collection"
            )
        for collection, entity_id in memberships.items():
            linked_id = _require_identifier(
                entity_id,
                field=f"person {collection} membership",
            )
            if linked_id not in identifiers[collection]:
                raise HouseholdValidationError(
                    f"person membership references absent {collection} id {linked_id!r}"
                )
    return normalized


def verify_legacy_household_mapping(
    mapping: LegacyHouseholdMapping,
    *,
    fingerprint_version: int,
    fingerprint_sha256: str,
    expected_household_id: UUID | None = None,
) -> None:
    """Validate one stored immutable legacy mapping without executing SQL."""

    if (
        mapping.fingerprint_version != fingerprint_version
        or mapping.fingerprint_sha256 != fingerprint_sha256
    ):
        raise LegacyHouseholdMappingIntegrityError(
            "legacy household identity was presented with different source content"
        )
    if (
        expected_household_id is not None
        and mapping.household_id != expected_household_id
    ):
        raise LegacyHouseholdMappingIntegrityError(
            "legacy household mapping does not match translated immutable content"
        )

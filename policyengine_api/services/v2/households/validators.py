"""Database-independent validation for v2 household operations."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from policyengine_api.spm import SPMSelection

if TYPE_CHECKING:
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
    value: Any,  # noqa: ANN401  # exact type() dispatch that mypy cannot narrow
    *,
    depth: int = 0,
    containers: frozenset[int] = frozenset(),
) -> object:
    """Reject values that are not standards-compliant JSON."""
    if depth > MAXIMUM_JSON_NESTING:
        msg = "JSON values must not exceed 100 nested containers"
        raise ValueError(msg)
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            msg = "JSON numbers must be finite"
            raise ValueError(msg)
        return value
    if type(value) not in {list, dict}:
        msg = "value must contain only standards-compliant JSON types"
        raise ValueError(msg)
    identity = id(value)
    if identity in containers:
        msg = "JSON values must not contain reference cycles"
        raise ValueError(msg)
    nested_containers = containers | {identity}
    if type(value) is list:
        for item in value:
            require_json_value(item, depth=depth + 1, containers=nested_containers)
        return value
    for key, item in value.items():
        if type(key) is not str:
            msg = "JSON object keys must be strings"
            raise ValueError(msg)
        require_json_value(item, depth=depth + 1, containers=nested_containers)
    return value


def _require_identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        msg = f"{field} must be a non-empty string of at most 255 characters"
        raise HouseholdValidationError(msg)
    return value


def _require_values(record: dict[str, Any], *, collection: str) -> None:
    values = record.get("values")
    if type(values) is not dict:
        msg = f"{collection} record values must be an object"
        raise HouseholdValidationError(msg)
    if len(values) > MAXIMUM_HOUSEHOLD_RECORD_VALUES:
        msg = (
            f"{collection} records must contain at most "
            f"{MAXIMUM_HOUSEHOLD_RECORD_VALUES} variable values"
        )
        raise HouseholdValidationError(msg)
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
        msg = f"unsupported country_id {country_id!r}"
        raise HouseholdValidationError(msg)
    if type(document) is not dict:
        msg = "household_data must be an object"
        raise HouseholdValidationError(msg)
    allowed = {"people", *collections}
    if country_id == "us":
        allowed.add("spm")
    unsupported = sorted(set(document) - allowed)
    if unsupported:
        msg = f"household_data contains unsupported collections: {unsupported}"
        raise HouseholdValidationError(msg)
    if "people" not in document:
        msg = "household_data must contain people"
        raise HouseholdValidationError(msg)

    normalized: dict[str, Any] = {}
    if "spm" in document:
        if type(document["spm"]) is not dict:
            msg = "spm must be an object"
            raise HouseholdValidationError(msg)
        try:
            SPMSelection.model_validate(document["spm"])
        except ValueError as error:
            msg = "spm selection is invalid"
            raise HouseholdValidationError(msg) from error
        # Saved selections are immutable identity, not a request to recertify
        # against whichever scientific bundle is currently installed.
        normalized["spm"] = dict(document["spm"])
    identifiers: dict[str, set[str]] = {}
    for collection in ("people", *collections):
        records = document.get(collection, [])
        if type(records) is not list:
            msg = f"{collection} must be a list"
            raise HouseholdValidationError(msg)
        if len(records) > MAXIMUM_HOUSEHOLD_ENTITIES:
            msg = (
                f"{collection} must contain at most "
                f"{MAXIMUM_HOUSEHOLD_ENTITIES} records"
            )
            raise HouseholdValidationError(msg)
        record_ids: set[str] = set()
        normalized_records: list[dict[str, Any]] = []
        expected_keys = (
            {"id", "source_name", "values", "memberships"}
            if collection == "people"
            else {"id", "source_name", "values"}
        )
        for record in records:
            if type(record) is not dict:
                msg = f"{collection} records must be objects"
                raise HouseholdValidationError(msg)
            unknown = sorted(set(record) - expected_keys)
            missing = sorted({"id", "values"} - set(record))
            if unknown or missing:
                msg = (
                    f"{collection} record fields are invalid: "
                    f"missing={missing}, unsupported={unknown}"
                )
                raise HouseholdValidationError(msg)
            record_id = _require_identifier(record["id"], field=f"{collection} id")
            if record_id in record_ids:
                msg = f"{collection} contains duplicate id {record_id!r}"
                raise HouseholdValidationError(msg)
            record_ids.add(record_id)
            _require_source_name(record, collection=collection)
            _require_values(record, collection=collection)
            if collection == "people" and type(record.get("memberships")) is not dict:
                msg = "people record memberships must be an object"
                raise HouseholdValidationError(msg)
            normalized_records.append(dict(record))
        identifiers[collection] = record_ids
        normalized[collection] = normalized_records

    required_memberships = set(collections)
    for person in normalized["people"]:
        memberships = person["memberships"]
        if not isinstance(memberships, dict):
            msg = "people record memberships must be an object"
            raise TypeError(msg)
        if set(memberships) != required_memberships:
            msg = (
                "people record memberships must identify every country-supported "
                "entity collection"
            )
            raise HouseholdValidationError(msg)
        for collection, entity_id in memberships.items():
            linked_id = _require_identifier(
                entity_id,
                field=f"person {collection} membership",
            )
            if linked_id not in identifiers[collection]:
                msg = (
                    f"person membership references absent {collection} id {linked_id!r}"
                )
                raise HouseholdValidationError(msg)
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
        msg = "legacy household identity was presented with different source content"
        raise LegacyHouseholdMappingIntegrityError(msg)
    if (
        expected_household_id is not None
        and mapping.household_id != expected_household_id
    ):
        msg = "legacy household mapping does not match translated immutable content"
        raise LegacyHouseholdMappingIntegrityError(msg)

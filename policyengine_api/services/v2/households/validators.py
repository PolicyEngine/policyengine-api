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
MAXIMUM_IDENTIFIER_LENGTH = 255
SUPPORTED_ENTITY_COLLECTIONS = {
    "us": ("household", "family", "tax_unit", "spm_unit", "marital_unit"),
    "uk": ("household", "benunit"),
}
PERSON_RECORD_FIELDS = frozenset({"id", "source_name", "values", "memberships"})
ENTITY_RECORD_FIELDS = frozenset({"id", "source_name", "values"})
REQUIRED_RECORD_FIELDS = frozenset({"id", "values"})


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
    _require_json_container(value, depth=depth, containers=containers)
    return value


def _require_json_container(
    container: list[Any] | dict[Any, Any],
    *,
    depth: int,
    containers: frozenset[int],
) -> None:
    """Check a JSON list's items or object's members, rejecting reference cycles.

    ``containers`` holds the identities of the containers enclosing this one.
    """
    identity = id(container)
    if identity in containers:
        msg = "JSON values must not contain reference cycles"
        raise ValueError(msg)
    nested_containers = containers | {identity}
    # The caller admits only exact lists and dicts, so isinstance is exact here.
    if isinstance(container, list):
        for item in container:
            require_json_value(item, depth=depth + 1, containers=nested_containers)
        return
    for key, item in container.items():
        if type(key) is not str:
            msg = "JSON object keys must be strings"
            raise ValueError(msg)
        require_json_value(item, depth=depth + 1, containers=nested_containers)


def _require_identifier(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAXIMUM_IDENTIFIER_LENGTH
    ):
        msg = (
            f"{field} must be a non-empty string of at most "
            f"{MAXIMUM_IDENTIFIER_LENGTH} characters"
        )
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
    collections = _require_supported_collections(country_id, document)

    normalized: dict[str, Any] = {}
    if "spm" in document:
        normalized["spm"] = _normalized_spm_selection(document["spm"])
    identifiers: dict[str, set[str]] = {}
    for collection in ("people", *collections):
        normalized_records, record_ids = _normalized_collection(
            collection, document.get(collection, [])
        )
        identifiers[collection] = record_ids
        normalized[collection] = normalized_records

    _require_complete_memberships(normalized["people"], collections, identifiers)
    return normalized


def _require_supported_collections(
    country_id: str,
    document: dict[str, Any],
) -> tuple[str, ...]:
    """Return the country's entity collections once the document fits them.

    The document must be an object with people and only the collections (and,
    for the US, the SPM selection) the country supports.
    """
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
    return collections


def _normalized_spm_selection(selection: object) -> dict[str, Any]:
    """Return a copy of a structurally valid saved SPM selection."""
    if type(selection) is not dict:
        msg = "spm must be an object"
        raise HouseholdValidationError(msg)
    try:
        SPMSelection.model_validate(selection)
    except ValueError as error:
        msg = "spm selection is invalid"
        raise HouseholdValidationError(msg) from error
    # Saved selections are immutable identity, not a request to recertify
    # against whichever scientific bundle is currently installed.
    return dict(selection)


def _normalized_collection(
    collection: str,
    records: object,
) -> tuple[list[dict[str, Any]], set[str]]:
    """Validate one collection's records; return copies of them and their ids."""
    if type(records) is not list:
        msg = f"{collection} must be a list"
        raise HouseholdValidationError(msg)
    if len(records) > MAXIMUM_HOUSEHOLD_ENTITIES:
        msg = f"{collection} must contain at most {MAXIMUM_HOUSEHOLD_ENTITIES} records"
        raise HouseholdValidationError(msg)
    record_ids: set[str] = set()
    normalized_records: list[dict[str, Any]] = []
    for record in records:
        record_id = _require_record_identity(record, collection=collection)
        if record_id in record_ids:
            msg = f"{collection} contains duplicate id {record_id!r}"
            raise HouseholdValidationError(msg)
        record_ids.add(record_id)
        _require_record_contents(record, collection=collection)
        normalized_records.append(dict(record))
    return normalized_records, record_ids


def _require_record_identity(record: object, *, collection: str) -> str:
    """Return the id of a record that has exactly its collection's fields."""
    if type(record) is not dict:
        msg = f"{collection} records must be objects"
        raise HouseholdValidationError(msg)
    expected_fields = (
        PERSON_RECORD_FIELDS if collection == "people" else ENTITY_RECORD_FIELDS
    )
    unknown = sorted(set(record) - expected_fields)
    missing = sorted(REQUIRED_RECORD_FIELDS - set(record))
    if unknown or missing:
        msg = (
            f"{collection} record fields are invalid: "
            f"missing={missing}, unsupported={unknown}"
        )
        raise HouseholdValidationError(msg)
    return _require_identifier(record["id"], field=f"{collection} id")


def _require_record_contents(record: dict[str, Any], *, collection: str) -> None:
    """Validate a record's source name, values and, for people, memberships."""
    _require_source_name(record, collection=collection)
    _require_values(record, collection=collection)
    if collection == "people" and type(record.get("memberships")) is not dict:
        msg = "people record memberships must be an object"
        raise HouseholdValidationError(msg)


def _require_complete_memberships(
    people: list[dict[str, Any]],
    collections: tuple[str, ...],
    identifiers: dict[str, set[str]],
) -> None:
    """Require every person to belong to one present record of each collection."""
    required_memberships = set(collections)
    for person in people:
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

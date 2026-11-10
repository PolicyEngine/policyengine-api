"""Database-independent validation for v2 household operations."""

from __future__ import annotations

import math
from enum import StrEnum
from functools import partial
from typing import TYPE_CHECKING, Any

from typing_extensions import override

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


class HouseholdValidationReason(StrEnum):
    """Which structural rule a household document breaks, as logs name it."""

    UNSUPPORTED_COUNTRY = "unsupported_country"
    DOCUMENT_NOT_OBJECT = "document_not_object"
    UNSUPPORTED_COLLECTIONS = "unsupported_collections"
    PEOPLE_MISSING = "people_missing"
    SPM_NOT_OBJECT = "spm_not_object"
    SPM_SELECTION_INVALID = "spm_selection_invalid"
    COLLECTION_NOT_LIST = "collection_not_list"
    TOO_MANY_RECORDS = "too_many_records"
    DUPLICATE_RECORD_ID = "duplicate_record_id"
    RECORD_NOT_OBJECT = "record_not_object"
    RECORD_FIELDS_INVALID = "record_fields_invalid"
    # An id, source name or membership that is not a short non-empty string.
    INVALID_IDENTIFIER = "invalid_identifier"
    VALUES_NOT_OBJECT = "values_not_object"
    TOO_MANY_VALUES = "too_many_values"
    MEMBERSHIPS_NOT_OBJECT = "memberships_not_object"
    # A person who does not belong to one record of each entity collection.
    INCOMPLETE_MEMBERSHIPS = "incomplete_memberships"
    ABSENT_MEMBERSHIP_TARGET = "absent_membership_target"


class LegacyHouseholdTranslationReason(StrEnum):
    """Why a v1 household cannot be translated exactly, as copy logs name it.

    A v1 household that translates into a document breaking a v2 rule takes
    that rule's HouseholdValidationReason instead.
    """

    UNSUPPORTED_COLLECTIONS = "legacy_unsupported_collections"
    PEOPLE_NOT_OBJECT = "legacy_people_not_object"
    GROUPS_NOT_OBJECT = "legacy_groups_not_object"
    GROUP_NOT_OBJECT = "legacy_group_not_object"
    MEMBERS_NOT_NAMED_PEOPLE = "legacy_members_not_named_people"
    PERSON_IN_MULTIPLE_GROUPS = "legacy_person_in_multiple_groups"
    PERSON_NOT_OBJECT = "legacy_person_not_object"
    AMBIGUOUS_DEFAULT_YEAR = "legacy_ambiguous_default_year"
    # The year the explicit periods give is outside the years v2 accepts.
    DEFAULT_YEAR_OUT_OF_RANGE = "legacy_default_year_out_of_range"
    # A period key policyengine-core parses but whose dates can't be computed.
    PERIOD_INVALID = "legacy_period_invalid"
    # A value that is not standards-compliant JSON (require_json_value), or
    # that the translated document nests too deeply.
    VALUE_NOT_JSON = "value_not_json"


class HouseholdValidationError(ValueError):
    """Raised when a household document violates its structural contract.

    ``reason`` names the broken rule. Unlike the message, which can quote the
    document's names, it holds nothing from the document, so logs record it.
    """

    def __init__(self, message: str, *, reason: HouseholdValidationReason) -> None:
        """Keep the message for the caller and the fixed reason for logs."""
        super().__init__(message)
        self.reason = reason

    @override
    def __reduce__(self) -> tuple[Any, ...]:
        """Tell copy and pickle to rebuild the error with its reason.

        ``BaseException`` rebuilds an error as ``type(error)(*error.args)``,
        which would leave out the keyword-only ``reason``.
        """
        return (partial(type(self), reason=self.reason), self.args, self.__dict__)


class HouseholdNotFoundError(LookupError):
    """Raised when a household UUID is absent from the selected country."""


class HouseholdCreationIntegrityError(RuntimeError):
    """Raised when stored content cannot support safe deduplication."""


class HouseholdContentHashCollisionError(HouseholdCreationIntegrityError):
    """Raised when one version and digest identify different canonical bytes."""


class LegacyHouseholdMappingIntegrityError(RuntimeError):
    """Raised when one immutable v1 identity maps inconsistently."""


class LegacyHouseholdTranslationError(ValueError):
    """Raised when committed v1 household data cannot be translated exactly.

    ``reason`` is a fixed code that copy failure logs record; the message,
    which can quote the household's names, is never logged.
    """

    def __init__(
        self,
        message: str,
        *,
        reason: LegacyHouseholdTranslationReason | HouseholdValidationReason,
    ) -> None:
        """Keep the message for debugging and the fixed reason for logs."""
        super().__init__(message)
        self.reason = reason

    @override
    def __reduce__(self) -> tuple[Any, ...]:
        """Tell copy and pickle to rebuild the error with its reason.

        ``BaseException`` rebuilds an error as ``type(error)(*error.args)``,
        which would leave out the keyword-only ``reason``.
        """
        return (partial(type(self), reason=self.reason), self.args, self.__dict__)


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
        raise HouseholdValidationError(
            msg, reason=HouseholdValidationReason.INVALID_IDENTIFIER
        )
    return value


def _require_values(record: dict[str, Any], *, collection: str) -> None:
    values = record.get("values")
    if type(values) is not dict:
        msg = f"{collection} record values must be an object"
        raise HouseholdValidationError(
            msg, reason=HouseholdValidationReason.VALUES_NOT_OBJECT
        )
    if len(values) > MAXIMUM_HOUSEHOLD_RECORD_VALUES:
        msg = (
            f"{collection} records must contain at most "
            f"{MAXIMUM_HOUSEHOLD_RECORD_VALUES} variable values"
        )
        raise HouseholdValidationError(
            msg, reason=HouseholdValidationReason.TOO_MANY_VALUES
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
        raise HouseholdValidationError(
            msg, reason=HouseholdValidationReason.UNSUPPORTED_COUNTRY
        )
    if type(document) is not dict:
        msg = "household_data must be an object"
        raise HouseholdValidationError(
            msg, reason=HouseholdValidationReason.DOCUMENT_NOT_OBJECT
        )
    allowed = {"people", *collections}
    if country_id == "us":
        allowed.add("spm")
    unsupported = sorted(set(document) - allowed)
    if unsupported:
        msg = f"household_data contains unsupported collections: {unsupported}"
        raise HouseholdValidationError(
            msg, reason=HouseholdValidationReason.UNSUPPORTED_COLLECTIONS
        )
    if "people" not in document:
        msg = "household_data must contain people"
        raise HouseholdValidationError(
            msg, reason=HouseholdValidationReason.PEOPLE_MISSING
        )
    return collections


def _normalized_spm_selection(selection: object) -> dict[str, Any]:
    """Return a copy of a structurally valid saved SPM selection."""
    if type(selection) is not dict:
        msg = "spm must be an object"
        raise HouseholdValidationError(
            msg, reason=HouseholdValidationReason.SPM_NOT_OBJECT
        )
    try:
        SPMSelection.model_validate(selection)
    except ValueError as error:
        msg = "spm selection is invalid"
        raise HouseholdValidationError(
            msg, reason=HouseholdValidationReason.SPM_SELECTION_INVALID
        ) from error
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
        raise HouseholdValidationError(
            msg, reason=HouseholdValidationReason.COLLECTION_NOT_LIST
        )
    if len(records) > MAXIMUM_HOUSEHOLD_ENTITIES:
        msg = f"{collection} must contain at most {MAXIMUM_HOUSEHOLD_ENTITIES} records"
        raise HouseholdValidationError(
            msg, reason=HouseholdValidationReason.TOO_MANY_RECORDS
        )
    record_ids: set[str] = set()
    normalized_records: list[dict[str, Any]] = []
    for record in records:
        record_id = _require_record_identity(record, collection=collection)
        if record_id in record_ids:
            msg = f"{collection} contains duplicate id {record_id!r}"
            raise HouseholdValidationError(
                msg, reason=HouseholdValidationReason.DUPLICATE_RECORD_ID
            )
        record_ids.add(record_id)
        _require_record_contents(record, collection=collection)
        normalized_records.append(dict(record))
    return normalized_records, record_ids


def _require_record_identity(record: object, *, collection: str) -> str:
    """Return the id of a record that has exactly its collection's fields."""
    if type(record) is not dict:
        msg = f"{collection} records must be objects"
        raise HouseholdValidationError(
            msg, reason=HouseholdValidationReason.RECORD_NOT_OBJECT
        )
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
        raise HouseholdValidationError(
            msg, reason=HouseholdValidationReason.RECORD_FIELDS_INVALID
        )
    return _require_identifier(record["id"], field=f"{collection} id")


def _require_record_contents(record: dict[str, Any], *, collection: str) -> None:
    """Validate a record's source name, values and, for people, memberships."""
    _require_source_name(record, collection=collection)
    _require_values(record, collection=collection)
    if collection == "people" and type(record.get("memberships")) is not dict:
        msg = "people record memberships must be an object"
        raise HouseholdValidationError(
            msg, reason=HouseholdValidationReason.MEMBERSHIPS_NOT_OBJECT
        )


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
            raise HouseholdValidationError(
                msg, reason=HouseholdValidationReason.INCOMPLETE_MEMBERSHIPS
            )
        for collection, entity_id in memberships.items():
            linked_id = _require_identifier(
                entity_id,
                field=f"person {collection} membership",
            )
            if linked_id not in identifiers[collection]:
                msg = (
                    f"person membership references absent {collection} id {linked_id!r}"
                )
                raise HouseholdValidationError(
                    msg, reason=HouseholdValidationReason.ABSENT_MEMBERSHIP_TARGET
                )


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

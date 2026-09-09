"""Router-facing and v1-copying services for immutable v2 households."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from sqlmodel import Session

from policyengine_api.services.v2.households.database_connectors.creates import (
    create_household,
    create_legacy_household_mapping,
)
from policyengine_api.services.v2.households.database_connectors.reads import (
    read_household_by_content_identity,
    read_household_row,
    read_household_rows,
    read_legacy_household_mapping,
)
from policyengine_api.services.v2.households.database_session import (
    HouseholdDatabaseSession,
)
from policyengine_api.services.v2.households.transformations import (
    LEGACY_HOUSEHOLD_FINGERPRINT_VERSION,
    canonical_household_document,
    canonicalize_household,
    household_page,
    household_read,
    legacy_household_fingerprint,
    stored_household_creation_input,
    translate_legacy_household,
)
from policyengine_api.services.v2.households.types import (
    CanonicalHouseholdContent,
    HouseholdCreationInput,
    HouseholdCreationResult,
    HouseholdPage,
    HouseholdRead,
    LegacyHouseholdPersistenceResult,
    LegacyHouseholdSnapshot,
    NativeHouseholdCreation,
    NativeHouseholdCreationInput,
)
from policyengine_api.services.v2.households.validators import (
    HouseholdContentHashCollisionError,
    HouseholdCreationIntegrityError,
    HouseholdNotFoundError,
    LegacyHouseholdMappingIntegrityError,
    normalize_household_document,
    verify_legacy_household_mapping,
)


def normalize_creation_input(
    household_input: HouseholdCreationInput,
) -> HouseholdCreationInput:
    document = household_input.household_data
    assert isinstance(document, dict)
    return HouseholdCreationInput(
        country_id=household_input.country_id,
        default_year=household_input.default_year,
        household_data=normalize_household_document(
            household_input.country_id,
            document,
        ),
    )


def create_normalized_household(
    session: Session,
    household_input: HouseholdCreationInput,
    *,
    canonicalizer: Callable[
        [HouseholdCreationInput], CanonicalHouseholdContent
    ] = canonicalize_household,
) -> HouseholdCreationResult:
    content = canonicalizer(household_input)
    created_id = create_household(
        session,
        household_input,
        canonicalization_version=content.version,
        content_hash=content.content_hash,
    )
    if created_id is not None:
        return HouseholdCreationResult(household_id=created_id, created=True)
    existing = read_household_by_content_identity(
        session,
        canonicalization_version=content.version,
        content_hash=content.content_hash,
    )
    if existing is None:
        raise HouseholdCreationIntegrityError(
            "household hash conflict did not resolve to a stored household"
        )
    if canonical_household_document(stored_household_creation_input(existing)) != (
        content.document
    ):
        raise HouseholdContentHashCollisionError(
            "stored household content differs for the same canonical version and hash"
        )
    return HouseholdCreationResult(household_id=existing.id, created=False)


def read_complete_household(
    session: Session, *, country_id: str, household_id: UUID
) -> HouseholdRead:
    household = read_household_row(
        session,
        country_id=country_id,
        household_id=household_id,
    )
    if household is None:
        raise HouseholdNotFoundError(f"household {household_id} was not found")
    return household_read(household)


def read_household_page(
    session: Session,
    *,
    country_id: str,
    default_year: int | None,
    offset: int,
    limit: int,
) -> HouseholdPage:
    return household_page(
        read_household_rows(
            session,
            country_id=country_id,
            default_year=default_year,
            offset=offset,
            limit=limit,
        ),
        offset=offset,
        limit=limit,
    )


def mirror_legacy_household_in_session(
    session: Session,
    snapshot: LegacyHouseholdSnapshot,
) -> LegacyHouseholdPersistenceResult:
    fingerprint = legacy_household_fingerprint(snapshot)
    existing = read_legacy_household_mapping(
        session,
        country_id=snapshot.country_id,
        legacy_household_id=snapshot.legacy_household_id,
        lock=True,
    )
    if existing is not None:
        verify_legacy_household_mapping(
            existing,
            fingerprint_version=LEGACY_HOUSEHOLD_FINGERPRINT_VERSION,
            fingerprint_sha256=fingerprint,
        )
    translated = translate_legacy_household(snapshot)
    normalized = normalize_creation_input(translated)
    result = create_normalized_household(session, normalized)
    if existing is not None:
        verify_legacy_household_mapping(
            existing,
            fingerprint_version=LEGACY_HOUSEHOLD_FINGERPRINT_VERSION,
            fingerprint_sha256=fingerprint,
            expected_household_id=result.household_id,
        )
        return LegacyHouseholdPersistenceResult(
            household_id=existing.household_id,
            household_created=False,
            mapping_created=False,
        )
    mapping_id = create_legacy_household_mapping(
        session,
        country_id=snapshot.country_id,
        legacy_household_id=snapshot.legacy_household_id,
        household_id=result.household_id,
        source_api_version=snapshot.api_version,
        fingerprint_version=LEGACY_HOUSEHOLD_FINGERPRINT_VERSION,
        fingerprint_sha256=fingerprint,
    )
    if mapping_id is not None:
        return LegacyHouseholdPersistenceResult(
            household_id=result.household_id,
            household_created=result.created,
            mapping_created=True,
        )
    concurrent = read_legacy_household_mapping(
        session,
        country_id=snapshot.country_id,
        legacy_household_id=snapshot.legacy_household_id,
        lock=False,
    )
    if concurrent is None:
        raise LegacyHouseholdMappingIntegrityError(
            "legacy household mapping conflict did not resolve to a stored row"
        )
    verify_legacy_household_mapping(
        concurrent,
        fingerprint_version=LEGACY_HOUSEHOLD_FINGERPRINT_VERSION,
        fingerprint_sha256=fingerprint,
        expected_household_id=result.household_id,
    )
    return LegacyHouseholdPersistenceResult(
        household_id=concurrent.household_id,
        household_created=False,
        mapping_created=False,
    )


class V2HouseholdService:
    def __init__(self, database_session: HouseholdDatabaseSession) -> None:
        self._database_session = database_session

    def create_household(
        self, household_input: NativeHouseholdCreationInput
    ) -> NativeHouseholdCreation:
        normalized = normalize_creation_input(
            HouseholdCreationInput.model_validate(household_input.model_dump())
        )
        with self._database_session.transaction() as session:
            result = create_normalized_household(session, normalized)
            item = read_complete_household(
                session,
                country_id=normalized.country_id,
                household_id=result.household_id,
            )
        return NativeHouseholdCreation(item=item, created=result.created)

    def get_household(self, *, country_id: str, household_id: UUID) -> HouseholdRead:
        with self._database_session.read() as session:
            return read_complete_household(
                session,
                country_id=country_id,
                household_id=household_id,
            )

    def list_households(
        self,
        *,
        country_id: str,
        default_year: int | None,
        offset: int,
        limit: int,
    ) -> HouseholdPage:
        with self._database_session.read() as session:
            return read_household_page(
                session,
                country_id=country_id,
                default_year=default_year,
                offset=offset,
                limit=limit,
            )

    def mirror_legacy_household(
        self, snapshot: LegacyHouseholdSnapshot
    ) -> LegacyHouseholdPersistenceResult:
        with self._database_session.transaction() as session:
            return mirror_legacy_household_in_session(session, snapshot)

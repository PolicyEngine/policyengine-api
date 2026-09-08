"""PostgreSQL transaction tests for household content and associations."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session

from policyengine_api.data.v2.migration_target import (
    V2_ALEMBIC_DISPOSABLE_TEST,
    load_v2_alembic_settings,
)
from policyengine_api.data.v2.models import (
    Household,
    LegacyHouseholdMapping,
    User,
    UserHouseholdAssociation,
)
from policyengine_api.data.v2.settings import V2_MIGRATION_DATABASE_URL
from policyengine_api.services.v2.households.services import (
    create_normalized_household,
    mirror_legacy_household_in_session,
    normalize_creation_input,
)
from policyengine_api.services.v2.households.transformations import (
    canonical_household_document,
    canonicalize_household,
)
from policyengine_api.services.v2.households.types import (
    CanonicalHouseholdContent,
    HouseholdCreationInput,
    LegacyHouseholdSnapshot,
)
from policyengine_api.services.v2.households.validators import (
    HouseholdContentHashCollisionError,
    LegacyHouseholdMappingIntegrityError,
)
from policyengine_api.services.v2.user_households.database_session import (
    UserHouseholdDatabaseSession,
)
from policyengine_api.services.v2.user_households.services import (
    V2UserHouseholdService,
)
from policyengine_api.services.v2.user_households.types import (
    UserHouseholdCreationInput,
    UserHouseholdUpdateInput,
)


def _disposable_url() -> str:
    database_url = os.environ.get(V2_MIGRATION_DATABASE_URL, "")
    if not database_url:
        pytest.skip(f"{V2_MIGRATION_DATABASE_URL} is not set")
    settings = load_v2_alembic_settings(
        {
            V2_MIGRATION_DATABASE_URL: database_url,
            V2_ALEMBIC_DISPOSABLE_TEST: os.environ.get(
                V2_ALEMBIC_DISPOSABLE_TEST,
                "",
            ),
        }
    )
    if not settings.disposable_test:
        pytest.fail("household persistence tests require disposable-test mode")
    return settings.url.render_as_string(hide_password=False)


def _normalized_input(marker: str, *, default_year: int | None = 2026):
    memberships = {
        "household": "household-1",
        "family": "family-1",
        "tax_unit": "tax-unit-1",
        "spm_unit": "spm-unit-1",
        "marital_unit": "marital-unit-1",
    }
    document: dict[str, object] = {
        "people": [
            {
                "id": "person-1",
                "values": {"stage11_marker": {"2026": marker}},
                "memberships": memberships,
            }
        ]
    }
    for collection, identifier in memberships.items():
        document[collection] = [{"id": identifier, "values": {}}]
    return normalize_creation_input(
        HouseholdCreationInput(
            country_id="us",
            default_year=default_year,
            household_data=document,
        )
    )


def _legacy_snapshot(legacy_id: int, marker: str, *, label: str):
    people = {"adult": {"stage11_marker": {"2026": marker}}}
    members = {"members": ["adult"]}
    return LegacyHouseholdSnapshot(
        country_id="us",
        legacy_household_id=legacy_id,
        label=label,
        api_version="1.0.0",
        household_json={
            "people": people,
            "households": {"home": members},
            "families": {"family": members},
            "tax_units": {"tax unit": members},
            "spm_units": {"spm unit": members},
            "marital_units": {"marital unit": members},
        },
        source_household_hash=f"source-{legacy_id}-{label}",
    )


def _cleanup(
    engine,
    *,
    household_ids: set[UUID],
    user_ids: set[UUID] | None = None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            delete(UserHouseholdAssociation).where(
                UserHouseholdAssociation.household_id.in_(household_ids)
            )
        )
        connection.execute(
            delete(LegacyHouseholdMapping).where(
                LegacyHouseholdMapping.household_id.in_(household_ids)
            )
        )
        connection.execute(delete(Household).where(Household.id.in_(household_ids)))
        if user_ids:
            connection.execute(delete(User).where(User.id.in_(user_ids)))


def test_concurrent_equivalent_content_resolves_to_one_household() -> None:
    engine = create_engine(_disposable_url())
    household_ids: set[UUID] = set()
    household_input = _normalized_input(f"concurrent-{uuid4()}")
    barrier = Barrier(2)

    def create_one() -> tuple[UUID, bool]:
        def synchronized_canonicalizer(command):
            content = canonicalize_household(command)
            barrier.wait(timeout=10)
            return content

        with Session(engine) as session, session.begin():
            result = create_normalized_household(
                session,
                household_input,
                canonicalizer=synchronized_canonicalizer,
            )
        return result.household_id, result.created

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _index: create_one(), range(2)))
        household_ids = {result[0] for result in results}

        assert len(household_ids) == 1
        assert sorted(result[1] for result in results) == [False, True]
        with Session(engine) as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(Household)
                    .where(Household.id.in_(household_ids))
                )
                == 1
            )
    finally:
        if household_ids:
            _cleanup(engine, household_ids=household_ids)
        engine.dispose()


def test_hash_collision_rolls_back_without_changing_stored_content() -> None:
    engine = create_engine(_disposable_url())
    household_ids: set[UUID] = set()
    original = _normalized_input(f"original-{uuid4()}")
    changed = _normalized_input(f"changed-{uuid4()}")
    try:
        with Session(engine) as session, session.begin():
            first = create_normalized_household(session, original)
            household_ids.add(first.household_id)
        original_identity = canonicalize_household(original)

        def simulated_collision(command) -> CanonicalHouseholdContent:
            return CanonicalHouseholdContent(
                version=original_identity.version,
                document=canonical_household_document(command),
                content_hash=original_identity.content_hash,
            )

        with Session(engine) as session, session.begin():
            with pytest.raises(HouseholdContentHashCollisionError):
                create_normalized_household(
                    session,
                    changed,
                    canonicalizer=simulated_collision,
                )

        with Session(engine) as session:
            stored = session.get(Household, first.household_id)
            assert stored is not None
            assert stored.household_data == original.household_data
    finally:
        if household_ids:
            _cleanup(engine, household_ids=household_ids)
        engine.dispose()


def test_legacy_mappings_are_many_to_one_and_conflicts_roll_back() -> None:
    engine = create_engine(_disposable_url())
    household_ids: set[UUID] = set()
    source_marker = f"legacy-{uuid4()}"
    first = _legacy_snapshot(910001, source_marker, label="First label")
    second = _legacy_snapshot(910002, source_marker, label="Second label")
    try:
        with Session(engine) as session, session.begin():
            first_result = mirror_legacy_household_in_session(session, first)
            second_result = mirror_legacy_household_in_session(session, second)
            household_ids.add(first_result.household_id)

        with Session(engine) as session, session.begin():
            retry = mirror_legacy_household_in_session(session, first)

        assert first_result.household_id == second_result.household_id
        assert retry.household_id == first_result.household_id
        assert retry.mapping_created is False

        conflicting = first.model_copy(update={"label": "Changed source label"})
        with Session(engine) as session, session.begin():
            with pytest.raises(LegacyHouseholdMappingIntegrityError):
                mirror_legacy_household_in_session(session, conflicting)

        with Session(engine) as session:
            mappings = session.scalars(
                select(LegacyHouseholdMapping).where(
                    LegacyHouseholdMapping.household_id == first_result.household_id
                )
            ).all()
            assert len(mappings) == 2
    finally:
        if household_ids:
            _cleanup(engine, household_ids=household_ids)
        engine.dispose()


def test_content_edit_creates_replacement_and_reassigns_named_association() -> None:
    engine = create_engine(_disposable_url())
    sessions = sessionmaker(engine, class_=Session, expire_on_commit=False)
    association_service = V2UserHouseholdService(UserHouseholdDatabaseSession(sessions))
    user_id = uuid4()
    household_ids: set[UUID] = set()
    try:
        with sessions.begin() as session:
            original = create_normalized_household(
                session,
                _normalized_input(f"before-edit-{uuid4()}"),
            )
            replacement = create_normalized_household(
                session,
                _normalized_input(f"after-edit-{uuid4()}"),
            )
            household_ids.update({original.household_id, replacement.household_id})
            session.add(User(id=user_id, primary_country="us"))

        first = association_service.create_user_household(
            UserHouseholdCreationInput(
                country_id="us",
                user_id=user_id,
                household_id=original.household_id,
                name="Application display label",
            )
        )
        duplicate = association_service.create_user_household(
            UserHouseholdCreationInput(
                country_id="us",
                user_id=user_id,
                household_id=original.household_id,
                name="Second saved entry",
            )
        )
        reassigned = association_service.patch_user_household(
            country_id="us",
            association_id=first.id,
            association_input=UserHouseholdUpdateInput(
                household_id=replacement.household_id,
                name="Edited application display label",
            ),
        )

        assert first.id != duplicate.id
        assert first.name == "Application display label"
        assert reassigned.id == first.id
        assert reassigned.household_id == replacement.household_id
        assert reassigned.name == "Edited application display label"
        assert {"name", "description", "label"}.isdisjoint(
            Household.__table__.columns.keys()
        )

        with pytest.raises(IntegrityError):
            with sessions.begin() as session:
                session.execute(
                    delete(Household).where(Household.id == original.household_id)
                )

        association_service.delete_user_household(
            country_id="us",
            association_id=first.id,
        )
        with sessions() as session:
            assert session.get(Household, original.household_id) is not None
            assert session.get(Household, replacement.household_id) is not None
    finally:
        if household_ids:
            _cleanup(
                engine,
                household_ids=household_ids,
                user_ids={user_id},
            )
        engine.dispose()

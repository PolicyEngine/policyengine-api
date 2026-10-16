"""Service tests for v2 user-policy associations."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlmodel import select

from policyengine_api.data.v2.models import (
    LegacyUserPolicyMapping,
    Policy,
    User,
    UserIdentity,
    UserPolicy,
)
from policyengine_api.services.v2.associations.validators import (
    AssociationReferenceConflictError,
    MirrorOwnedAssociationError,
)
from policyengine_api.services.v2.legacy_refs.validators import (
    LegacyReferenceNotFoundError,
)
from policyengine_api.services.v2.user_policies.database_session import (
    UserPolicyDatabaseSession,
)
from policyengine_api.services.v2.user_policies.services import V2UserPolicyService
from policyengine_api.services.v2.user_policies.transformations import (
    project_legacy_user_policy,
)
from policyengine_api.services.v2.user_policies.types import (
    LegacyUserPolicySnapshot,
    UserPolicyCreateFields,
    UserPolicyUpdateInput,
)
from policyengine_api.services.v2.user_policies.validators import (
    AssociationCountryConflictError,
    AssociationPolicyNotFoundError,
    UserPolicyNotFoundError,
)
from tests.unit.v2.user_service_support import (
    ALICE,
    BOB,
    MAPPED_LEGACY_POLICY_ID,
    default_legacy_references,
    v2_store,
)


@pytest.fixture
def store():
    with v2_store() as selected:
        legacy_references = default_legacy_references()
        service = V2UserPolicyService(
            UserPolicyDatabaseSession(selected.sessions),
            legacy_references,
        )
        yield service, selected, legacy_references


def _fields(**changes) -> UserPolicyCreateFields:
    values: dict[str, object] = {
        "country_id": "us",
        "legacy_policy_id": 1,
        "name": "Saved reform",
        "description": "Personal note",
    }
    values.update(changes)
    return UserPolicyCreateFields.model_validate(values)


def test_first_save_provisions_the_owner_and_stores_v3_fields(store) -> None:
    service, selected, legacy_references = store

    created = service.create_user_policy(
        principal=ALICE,
        association_input=_fields(
            baseline="current-policy",
            provenance={"source": "bill", "ref": "HR-1"},
        ),
    )

    assert created.policy_id is None
    assert created.legacy_policy_id == 1
    assert created.baseline == "current-policy"
    assert created.provenance == {"source": "bill", "ref": "HR-1", "confidence": None}
    with selected.sessions() as session:
        identity = session.exec(select(UserIdentity)).one()
        user = session.get(User, identity.user_id)
        assert (identity.issuer, identity.subject) == (ALICE.issuer, ALICE.subject)
        assert created.user_id == identity.user_id
        assert user is not None and user.primary_country == "us"
    assert legacy_references.calls == [("us", {"policy": [1]})]


def test_legacy_reference_resolves_the_mirrored_v2_policy(store) -> None:
    service, selected, _legacy_references = store

    mapped = service.create_user_policy(
        principal=ALICE,
        association_input=_fields(legacy_policy_id=MAPPED_LEGACY_POLICY_ID),
    )
    explicit = service.create_user_policy(
        principal=ALICE,
        association_input=_fields(
            legacy_policy_id=MAPPED_LEGACY_POLICY_ID,
            policy_id=selected.policy_id,
        ),
    )
    v2_only = service.create_user_policy(
        principal=ALICE,
        association_input=UserPolicyCreateFields(
            country_id="us", policy_id=selected.policy_id
        ),
    )

    assert mapped.policy_id == explicit.policy_id == v2_only.policy_id
    assert mapped.policy_id == selected.policy_id
    assert v2_only.legacy_policy_id is None


def test_create_rejects_bad_references_before_writing(store) -> None:
    service, selected, _legacy_references = store

    with pytest.raises(LegacyReferenceNotFoundError, match="v1 policy 404"):
        service.create_user_policy(
            principal=ALICE, association_input=_fields(legacy_policy_id=404)
        )
    with pytest.raises(LegacyReferenceNotFoundError):
        service.create_user_policy(
            principal=ALICE,
            association_input=_fields(country_id="uk", legacy_policy_id=1),
        )
    with pytest.raises(AssociationPolicyNotFoundError):
        service.create_user_policy(
            principal=ALICE,
            association_input=_fields(
                legacy_policy_id=None,
                policy_id=UUID("00000000-0000-0000-0000-000000000099"),
            ),
        )
    with pytest.raises(AssociationCountryConflictError):
        service.create_user_policy(
            principal=ALICE,
            association_input=_fields(
                legacy_policy_id=None, policy_id=selected.uk_policy_id
            ),
        )
    with pytest.raises(AssociationReferenceConflictError):
        service.create_user_policy(
            principal=ALICE,
            association_input=_fields(
                legacy_policy_id=MAPPED_LEGACY_POLICY_ID,
                policy_id=selected.uk_policy_id,
                country_id="us",
            ),
        )

    with selected.sessions() as session:
        assert session.exec(select(UserPolicy)).all() == []
        assert session.exec(select(User)).all() == []


def test_other_users_rows_are_not_found_and_lists_are_owner_scoped(store) -> None:
    service, _selected, _legacy_references = store
    alice_row = service.create_user_policy(
        principal=ALICE, association_input=_fields(name="Alice")
    )
    service.create_user_policy(principal=BOB, association_input=_fields(name="Bob"))
    service.create_user_policy(
        principal=ALICE, association_input=_fields(name="Alice 2", legacy_policy_id=2)
    )

    for operation in (
        lambda: service.get_user_policy(
            principal=BOB, country_id="us", association_id=alice_row.id
        ),
        lambda: service.patch_user_policy(
            principal=BOB,
            country_id="us",
            association_id=alice_row.id,
            association_input=UserPolicyUpdateInput(name="stolen"),
        ),
        lambda: service.delete_user_policy(
            principal=BOB, country_id="us", association_id=alice_row.id
        ),
        lambda: service.get_user_policy(
            principal=ALICE, country_id="uk", association_id=alice_row.id
        ),
    ):
        with pytest.raises(UserPolicyNotFoundError):
            operation()

    page = service.list_user_policies(principal=ALICE, country_id="us", limit=1)
    filtered = service.list_user_policies(
        principal=ALICE, country_id="us", legacy_policy_id=2
    )
    assert [item.name for item in page.items] == ["Alice"]
    assert page.has_more is True
    assert [item.name for item in filtered.items] == ["Alice 2"]
    assert service.get_user_policy(
        principal=ALICE, country_id="us", association_id=alice_row.id
    ).name == ("Alice")


def test_repointing_re_resolves_or_clears_the_v2_reference(store) -> None:
    service, selected, legacy_references = store
    created = service.create_user_policy(principal=ALICE, association_input=_fields())

    mapped = service.patch_user_policy(
        principal=ALICE,
        country_id="us",
        association_id=created.id,
        association_input=UserPolicyUpdateInput(
            legacy_policy_id=MAPPED_LEGACY_POLICY_ID
        ),
    )
    cleared = service.patch_user_policy(
        principal=ALICE,
        country_id="us",
        association_id=created.id,
        association_input=UserPolicyUpdateInput(legacy_policy_id=3, description=None),
    )
    renamed = service.patch_user_policy(
        principal=ALICE,
        country_id="us",
        association_id=created.id,
        association_input=UserPolicyUpdateInput(name="Renamed"),
    )

    assert (mapped.legacy_policy_id, mapped.policy_id) == (
        MAPPED_LEGACY_POLICY_ID,
        selected.policy_id,
    )
    assert (cleared.legacy_policy_id, cleared.policy_id) == (3, None)
    assert cleared.description is None
    assert (renamed.legacy_policy_id, renamed.policy_id, renamed.name) == (
        3,
        None,
        "Renamed",
    )
    with pytest.raises(LegacyReferenceNotFoundError):
        service.patch_user_policy(
            principal=ALICE,
            country_id="us",
            association_id=created.id,
            association_input=UserPolicyUpdateInput(legacy_policy_id=404),
        )
    assert legacy_references.calls[-1] == ("us", {"policy": [404]})


def test_rows_owned_by_the_stage_10_mirror_conflict(store) -> None:
    service, selected, _legacy_references = store
    created = service.create_user_policy(principal=ALICE, association_input=_fields())
    with selected.sessions.begin() as session:
        session.add(
            LegacyUserPolicyMapping(
                country_id="us",
                legacy_user_policy_id=42,
                user_policy_id=created.id,
                fingerprint_version=1,
                fingerprint_sha256="b" * 64,
            )
        )

    with pytest.raises(MirrorOwnedAssociationError):
        service.patch_user_policy(
            principal=ALICE,
            country_id="us",
            association_id=created.id,
            association_input=UserPolicyUpdateInput(name="Renamed"),
        )
    with pytest.raises(MirrorOwnedAssociationError):
        service.delete_user_policy(
            principal=ALICE, country_id="us", association_id=created.id
        )
    assert service.get_user_policy(
        principal=ALICE, country_id="us", association_id=created.id
    ).name == ("Saved reform")


def test_delete_removes_only_the_association(store) -> None:
    service, selected, _legacy_references = store
    created = service.create_user_policy(
        principal=ALICE,
        association_input=_fields(legacy_policy_id=MAPPED_LEGACY_POLICY_ID),
    )

    service.delete_user_policy(
        principal=ALICE, country_id="us", association_id=created.id
    )

    with selected.sessions() as session:
        assert session.get(UserPolicy, created.id) is None
        assert session.get(Policy, selected.policy_id) is not None
        assert session.get(User, created.user_id) is not None


def test_stage_10_projection_records_the_v1_reform_id() -> None:
    snapshot = LegacyUserPolicySnapshot.model_validate(
        {
            "country_id": "us",
            "legacy_user_policy_id": 10,
            "reform_id": 95762,
            "reform_label": "Reform",
            "baseline_id": 2,
            "baseline_label": None,
            "user_id": "auth0|legacy",
            "year": "2026",
            "geography": "us",
            "dataset": None,
            "number_of_provisions": 1,
            "api_version": "1.0.0",
            "added_date": 1,
            "updated_date": 2,
        }
    )
    policy_id = UUID("00000000-0000-0000-0000-000000000010")
    user_id = UUID("00000000-0000-0000-0000-000000000070")

    projection = project_legacy_user_policy(
        snapshot, user_id=user_id, policy_id=policy_id
    )

    assert projection.legacy_policy_id == 95762
    assert projection.policy_id == policy_id


def test_patch_input_requires_a_supported_field() -> None:
    with pytest.raises(ValueError):
        UserPolicyUpdateInput()
    with pytest.raises(ValueError):
        UserPolicyUpdateInput.model_validate(
            {"policy_id": "00000000-0000-0000-0000-000000000001"}
        )
    with pytest.raises(ValueError):
        UserPolicyUpdateInput(legacy_policy_id=None)

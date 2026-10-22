"""Pin the statements and writes that copy one v1 saved-policy revision into v2."""

from __future__ import annotations

from collections import deque
from types import SimpleNamespace
from uuid import UUID

import pytest

from policyengine_api.data.v2.models import LegacyUserPolicyMapping, UserPolicy
from policyengine_api.services.v2.policies import services as policy_services
from policyengine_api.services.v2.policies.types import LegacyPolicySnapshot
from policyengine_api.services.v2.user_policies import services
from policyengine_api.services.v2.user_policies.transformations import (
    USER_POLICY_FINGERPRINT_VERSION,
    fingerprint_legacy_user_policy,
)
from policyengine_api.services.v2.user_policies.types import LegacyUserPolicySnapshot
from policyengine_api.services.v2.user_policies.validators import (
    LegacyUserPolicyIntegrityError,
)
from tests.fixtures.recording_session import RecordingSession

POLICY_ID = UUID("00000000-0000-0000-0000-000000000010")
USER_ID = UUID("00000000-0000-0000-0000-000000000070")
ASSOCIATION_ID = UUID("00000000-0000-0000-0000-000000000060")
MAPPING_ID = UUID("00000000-0000-0000-0000-000000000099")
MAPPING_COLUMNS = (
    "legacy_user_policy_mappings.id, legacy_user_policy_mappings.created_at, "
    "legacy_user_policy_mappings.updated_at, legacy_user_policy_mappings.country_id, "
    "legacy_user_policy_mappings.legacy_user_policy_id, "
    "legacy_user_policy_mappings.user_policy_id, "
    "legacy_user_policy_mappings.last_applied_source_revision, "
    "legacy_user_policy_mappings.fingerprint_version, "
    "legacy_user_policy_mappings.fingerprint_sha256"
)
SELECT_MAPPING = (
    f"SELECT {MAPPING_COLUMNS} \nFROM legacy_user_policy_mappings \n"
    "WHERE legacy_user_policy_mappings.country_id = %(country_id_1)s::VARCHAR AND "
    "legacy_user_policy_mappings.legacy_user_policy_id = "
    "%(legacy_user_policy_id_1)s::BIGINT"
)
SELECT_MAPPING_FOR_UPDATE = f"{SELECT_MAPPING} FOR UPDATE"
MAPPING_LOOKUP = {"country_id_1": "us", "legacy_user_policy_id_1": 10}
SELECT_MAPPED_ASSOCIATION = (
    "SELECT user_policy_associations.id, user_policy_associations.created_at, "
    "user_policy_associations.updated_at, user_policy_associations.user_id, "
    "user_policy_associations.policy_id, "
    "user_policy_associations.legacy_policy_id, "
    "user_policy_associations.country_id, user_policy_associations.name, "
    "user_policy_associations.description, user_policy_associations.baseline, "
    "user_policy_associations.provenance \nFROM user_policy_associations \n"
    "WHERE user_policy_associations.id = %(id_1)s::UUID AND "
    "user_policy_associations.country_id = %(country_id_1)s::VARCHAR"
)
INSERT_MAPPING = (
    "INSERT INTO legacy_user_policy_mappings (id, created_at, updated_at, "
    "country_id, legacy_user_policy_id, user_policy_id, "
    "last_applied_source_revision, fingerprint_version, fingerprint_sha256) "
    "VALUES (%(id)s::UUID, %(created_at)s::TIMESTAMP WITH TIME ZONE, "
    "%(updated_at)s::TIMESTAMP WITH TIME ZONE, %(country_id)s::VARCHAR, "
    "%(legacy_user_policy_id)s::BIGINT, %(user_policy_id)s::UUID, "
    "%(last_applied_source_revision)s::BIGINT, %(fingerprint_version)s::INTEGER, "
    "%(fingerprint_sha256)s::VARCHAR) ON CONFLICT ON CONSTRAINT "
    "uq_legacy_user_policy_mappings_country_legacy DO NOTHING RETURNING "
    "legacy_user_policy_mappings.id"
)


def _snapshot() -> LegacyUserPolicySnapshot:
    return LegacyUserPolicySnapshot(
        country_id="us",
        legacy_user_policy_id=10,
        reform_id=2,
        reform_label="Renamed reform",
        baseline_id=1,
        user_id="auth0|one",
        year="2026",
        geography="us",
        number_of_provisions=3,
        api_version="1.0.0",
        added_date=1,
        updated_date=2,
    )


FINGERPRINT = fingerprint_legacy_user_policy(_snapshot())


@pytest.fixture(autouse=True)
def resolved_policy_and_user(monkeypatch) -> None:
    # mirror_legacy_user_policy_in_session imports this function when it runs,
    # so it is replaced in the module that defines it.
    monkeypatch.setattr(
        policy_services,
        "mirror_legacy_policy_in_session",
        lambda _session, _reform: SimpleNamespace(policy_id=POLICY_ID),
    )
    monkeypatch.setattr(
        services, "resolve_legacy_user_id", lambda _session, **_kwargs: USER_ID
    )


def _mirror(
    session: RecordingSession,
    *,
    source_revision: int = 1,
    changed_fields: frozenset[str] = frozenset(),
):
    return services.mirror_legacy_user_policy_in_session(
        session,
        _snapshot(),
        LegacyPolicySnapshot(
            country_id="us",
            legacy_policy_id=2,
            api_version="1.0.0",
            policy_json={},
            source_policy_hash="legacy-hash",
        ),
        source_revision=source_revision,
        changed_fields=changed_fields,
    )


def _mapping(**changes: object) -> LegacyUserPolicyMapping:
    fields: dict[str, object] = {
        "country_id": "us",
        "legacy_user_policy_id": 10,
        "user_policy_id": ASSOCIATION_ID,
        "last_applied_source_revision": 1,
        "fingerprint_version": USER_POLICY_FINGERPRINT_VERSION,
        "fingerprint_sha256": "a" * 64,
    }
    fields.update(changes)
    return LegacyUserPolicyMapping(**fields)


def _association(**changes: object) -> UserPolicy:
    fields: dict[str, object] = {
        "id": ASSOCIATION_ID,
        "country_id": "us",
        "user_id": USER_ID,
        "policy_id": POLICY_ID,
        "name": "Native name",
    }
    fields.update(changes)
    return UserPolicy(**fields)


def _mapping_insert(user_policy_id: UUID, source_revision: int) -> tuple:
    return (
        "execute",
        INSERT_MAPPING,
        {
            "id": None,
            "created_at": None,
            "updated_at": None,
            "country_id": "us",
            "legacy_user_policy_id": 10,
            "user_policy_id": user_policy_id,
            "last_applied_source_revision": source_revision,
            "fingerprint_version": USER_POLICY_FINGERPRINT_VERSION,
            "fingerprint_sha256": FINGERPRINT,
        },
    )


def test_new_revision_creates_the_association_and_its_mapping() -> None:
    session = RecordingSession(results=deque([None, MAPPING_ID]))

    result = _mirror(session, source_revision=1)

    created = session.operations[1][1]
    assert session.operations == [
        ("exec", SELECT_MAPPING_FOR_UPDATE, MAPPING_LOOKUP),
        ("add", created),
        ("flush",),
        ("refresh", created),
        _mapping_insert(created.id, 1),
    ]
    assert (created.country_id, created.user_id, created.policy_id) == (
        "us",
        USER_ID,
        POLICY_ID,
    )
    assert created.name == "Renamed reform"
    assert result == services.LegacyUserPolicyPersistenceResult(
        association_id=created.id,
        policy_id=POLICY_ID,
        association_created=True,
        association_updated=False,
        mapping_created=True,
    )


def test_lost_mapping_race_deletes_its_association_and_applies_the_winner() -> None:
    winner = _mapping(last_applied_source_revision=1)
    association = _association()
    session = RecordingSession(results=deque([None, None, winner, association]))

    result = _mirror(session, source_revision=2, changed_fields=frozenset({"year"}))

    created = session.operations[1][1]
    assert session.operations == [
        ("exec", SELECT_MAPPING_FOR_UPDATE, MAPPING_LOOKUP),
        ("add", created),
        ("flush",),
        ("refresh", created),
        _mapping_insert(created.id, 2),
        ("delete", created),
        ("flush",),
        ("exec", SELECT_MAPPING, MAPPING_LOOKUP),
        (
            "exec",
            SELECT_MAPPED_ASSOCIATION,
            {"id_1": ASSOCIATION_ID, "country_id_1": "us"},
        ),
        ("add", winner),
        ("flush",),
    ]
    assert association.name == "Native name"
    assert winner.fingerprint_sha256 == FINGERPRINT
    assert winner.last_applied_source_revision == 2
    assert result == services.LegacyUserPolicyPersistenceResult(
        association_id=ASSOCIATION_ID,
        policy_id=POLICY_ID,
        association_created=False,
        association_updated=False,
        mapping_created=False,
    )


def test_lost_mapping_race_without_a_stored_winner_is_an_integrity_error() -> None:
    session = RecordingSession(results=deque([None, None, None]))

    with pytest.raises(
        LegacyUserPolicyIntegrityError,
        match=r"^legacy user-policy mapping conflict did not resolve to a stored row$",
    ):
        _mirror(session)

    assert [operation[0] for operation in session.operations] == [
        "exec",
        "add",
        "flush",
        "refresh",
        "execute",
        "delete",
        "flush",
        "exec",
    ]


def test_next_revision_with_a_new_reform_label_renames_the_association() -> None:
    mapping = _mapping(last_applied_source_revision=1)
    association = _association()
    session = RecordingSession(results=deque([mapping, association]))

    result = _mirror(
        session, source_revision=2, changed_fields=frozenset({"reform_label"})
    )

    assert session.operations == [
        ("exec", SELECT_MAPPING_FOR_UPDATE, MAPPING_LOOKUP),
        (
            "exec",
            SELECT_MAPPED_ASSOCIATION,
            {"id_1": ASSOCIATION_ID, "country_id_1": "us"},
        ),
        ("add", association),
        ("add", mapping),
        ("flush",),
    ]
    assert association.name == "Renamed reform"
    assert mapping.last_applied_source_revision == 2
    assert mapping.fingerprint_sha256 == FINGERPRINT
    assert result.association_updated is True
    assert result.association_created is False
    assert result.mapping_created is False


@pytest.mark.parametrize(
    ("stored_revision", "stored_fingerprint"),
    [(3, "a" * 64), (2, FINGERPRINT)],
)
def test_stale_or_replayed_revisions_write_nothing(
    stored_revision: int,
    stored_fingerprint: str,
) -> None:
    mapping = _mapping(
        last_applied_source_revision=stored_revision,
        fingerprint_sha256=stored_fingerprint,
    )
    session = RecordingSession(results=deque([mapping, _association()]))

    result = _mirror(
        session, source_revision=2, changed_fields=frozenset({"reform_label"})
    )

    assert [operation[0] for operation in session.operations] == ["exec", "exec"]
    assert mapping.last_applied_source_revision == stored_revision
    assert result == services.LegacyUserPolicyPersistenceResult(
        association_id=ASSOCIATION_ID,
        policy_id=POLICY_ID,
        association_created=False,
        association_updated=False,
        mapping_created=False,
    )


@pytest.mark.parametrize(
    ("mapping_changes", "association", "message"),
    [
        ({}, None, "legacy user-policy mapping has no association"),
        (
            {},
            _association(policy_id=UUID(int=1)),
            "legacy user-policy mapping conflicts with immutable association fields",
        ),
        (
            {},
            _association(country_id="uk"),
            "legacy user-policy mapping conflicts with immutable association fields",
        ),
        (
            {},
            _association(user_id=UUID(int=1)),
            "legacy user-policy mapping conflicts with immutable association fields",
        ),
        (
            {"fingerprint_version": USER_POLICY_FINGERPRINT_VERSION + 1},
            _association(),
            "legacy user-policy fingerprint version is unsupported",
        ),
        (
            {"last_applied_source_revision": 2},
            _association(),
            "legacy user-policy revision conflicts with its stored fingerprint",
        ),
        (
            {"last_applied_source_revision": 0},
            _association(),
            "legacy user-policy revision has an unapplied predecessor",
        ),
    ],
)
def test_inconsistent_existing_mappings_are_integrity_errors(
    mapping_changes: dict[str, object],
    association: UserPolicy | None,
    message: str,
) -> None:
    session = RecordingSession(
        results=deque([_mapping(**mapping_changes), association])
    )

    with pytest.raises(LegacyUserPolicyIntegrityError, match=rf"^{message}$"):
        _mirror(session, source_revision=2)

    assert [operation[0] for operation in session.operations] == ["exec", "exec"]

"""Legacy saved-policy fingerprint and projection command tests."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID

import pytest

from policyengine_api.data.v2.models import LegacyUserPolicyMapping, UserPolicy
from policyengine_api.services.v2.user_policies.legacy_service import (
    LegacyUserPolicyIntegrityError,
    apply_existing_legacy_user_policy_mapping,
)
from policyengine_api.services.v2.user_policies.legacy_translation import (
    USER_POLICY_FINGERPRINT_VERSION,
    LegacyUserPolicySnapshot,
    fingerprint_legacy_user_policy,
)


POLICY_ID = UUID("00000000-0000-0000-0000-000000000010")
USER_ID = UUID("00000000-0000-0000-0000-000000000070")


def _snapshot(**changes) -> LegacyUserPolicySnapshot:
    values = {
        "country_id": "us",
        "legacy_user_policy_id": 10,
        "reform_id": 2,
        "reform_label": "Reform",
        "baseline_id": 1,
        "baseline_label": "Current law",
        "user_id": "auth0|one",
        "year": "2026",
        "geography": "us",
        "dataset": "enhanced_cps_2024",
        "number_of_provisions": 3,
        "api_version": "1.0.0",
        "added_date": 1,
        "updated_date": 2,
        "budgetary_impact": None,
        "type": None,
    }
    values.update(changes)
    return LegacyUserPolicySnapshot.model_validate(values)


def test_complete_row_fingerprint_is_deterministic_and_sha256() -> None:
    first = _snapshot()
    reordered = LegacyUserPolicySnapshot.model_validate(
        dict(reversed(list(first.model_dump().items())))
    )

    assert fingerprint_legacy_user_policy(first) == fingerprint_legacy_user_policy(
        reordered
    )
    assert len(fingerprint_legacy_user_policy(first)) == 64


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("reform_label", "Updated"),
        ("baseline_label", "Baseline updated"),
        ("year", "2027"),
        ("geography", "ca"),
        ("dataset", None),
        ("number_of_provisions", 4),
        ("api_version", "2.0.0"),
        ("added_date", 3),
        ("updated_date", 4),
        ("budgetary_impact", "100"),
        ("type", "reform"),
    ],
)
def test_every_mutable_or_v1_only_field_changes_the_fingerprint(
    field: str,
    value: object,
) -> None:
    assert fingerprint_legacy_user_policy(_snapshot()) != (
        fingerprint_legacy_user_policy(_snapshot(**{field: value}))
    )


def test_snapshot_rejects_unknown_or_unbounded_fields() -> None:
    with pytest.raises(ValueError):
        _snapshot(unexpected="value")
    with pytest.raises(ValueError):
        _snapshot(user_id="x" * 256)


def _apply_update(
    *,
    changed_fields: frozenset[str],
    stored_revision: int = 0,
    source_revision: int = 1,
    stored_fingerprint: str = "a" * 64,
    fingerprint: str = "b" * 64,
):
    association = UserPolicy(
        country_id="us",
        user_id=USER_ID,
        policy_id=POLICY_ID,
        name="Native name",
        description="Native description",
    )
    mapping = LegacyUserPolicyMapping(
        country_id="us",
        legacy_user_policy_id=10,
        user_policy_id=association.id,
        last_applied_source_revision=stored_revision,
        fingerprint_version=USER_POLICY_FINGERPRINT_VERSION,
        fingerprint_sha256=stored_fingerprint,
    )
    session = MagicMock()
    session.exec.return_value.one_or_none.return_value = association
    result = apply_existing_legacy_user_policy_mapping(
        session,
        mapping=mapping,
        country_id="us",
        reform_label="Legacy rename",
        fingerprint=fingerprint,
        user_id=USER_ID,
        policy_id=POLICY_ID,
        changed_fields=changed_fields,
        source_revision=source_revision,
    )
    return association, mapping, result


def test_v1_only_update_advances_fingerprint_without_changing_presentation() -> None:
    association, mapping, result = _apply_update(
        changed_fields=frozenset({"year", "updated_date"})
    )

    assert result.association_updated is False
    assert association.name == "Native name"
    assert association.description == "Native description"
    assert mapping.fingerprint_sha256 == "b" * 64
    assert mapping.last_applied_source_revision == 1


def test_reform_label_update_changes_only_name() -> None:
    association, mapping, result = _apply_update(
        changed_fields=frozenset({"reform_label", "updated_date"})
    )

    assert result.association_updated is True
    assert association.name == "Legacy rename"
    assert association.description == "Native description"
    assert mapping.fingerprint_sha256 == "b" * 64
    assert mapping.last_applied_source_revision == 1


def test_same_revision_and_fingerprint_is_an_idempotent_replay() -> None:
    association, mapping, result = _apply_update(
        changed_fields=frozenset({"reform_label"}),
        stored_revision=3,
        source_revision=3,
        stored_fingerprint="b" * 64,
    )

    assert result.association_updated is False
    assert association.name == "Native name"
    assert mapping.last_applied_source_revision == 3


def test_same_revision_with_different_fingerprint_is_rejected() -> None:
    with pytest.raises(LegacyUserPolicyIntegrityError, match="revision conflicts"):
        _apply_update(
            changed_fields=frozenset({"reform_label"}),
            stored_revision=3,
            source_revision=3,
        )


def test_stale_revision_is_an_idempotent_no_op() -> None:
    association, mapping, result = _apply_update(
        changed_fields=frozenset({"reform_label"}),
        stored_revision=3,
        source_revision=2,
    )

    assert result.association_updated is False
    assert association.name == "Native name"
    assert mapping.last_applied_source_revision == 3


def test_revision_with_an_unapplied_predecessor_is_rejected() -> None:
    with pytest.raises(LegacyUserPolicyIntegrityError, match="unapplied predecessor"):
        _apply_update(
            changed_fields=frozenset({"reform_label"}),
            stored_revision=1,
            source_revision=3,
        )

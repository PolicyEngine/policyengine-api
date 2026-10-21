"""Pin how a retained saved-policy mirror event is decoded or rejected."""

from __future__ import annotations

import pytest

from policyengine_api.data.v1_models import UserPolicyMirrorEvent
from policyengine_api.services.user_policy_service import (
    PendingUserPolicyMirrorEvent,
    UserPolicyMirrorEventIntegrityError,
    UserPolicyService,
)
from policyengine_api.services.v2.user_policies.transformations import (
    fingerprint_legacy_user_policy,
)
from policyengine_api.services.v2.user_policies.types import LegacyUserPolicySnapshot

SNAPSHOT = LegacyUserPolicySnapshot(
    country_id="us",
    legacy_user_policy_id=10,
    reform_id=2,
    baseline_id=1,
    user_id="auth0|one",
    year="2026",
    geography="us",
    number_of_provisions=3,
    api_version="1.0.0",
    added_date=1,
    updated_date=2,
)


def _event(**changes: object) -> UserPolicyMirrorEvent:
    fields: dict[str, object] = {
        "id": 7,
        "country_id": "us",
        "legacy_user_policy_id": 10,
        "source_revision": 2,
        "event_type": "update",
        "payload_schema_version": 1,
        "payload_json": {
            "snapshot": SNAPSHOT.model_dump(mode="json"),
            "changed_fields": ["reform_label", "year"],
        },
        "source_fingerprint_sha256": fingerprint_legacy_user_policy(SNAPSHOT),
    }
    fields.update(changes)
    return UserPolicyMirrorEvent(**fields)


def _payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "snapshot": SNAPSHOT.model_dump(mode="json"),
        "changed_fields": ["reform_label", "year"],
    }
    payload.update(changes)
    return payload


def test_valid_update_event_decodes_to_its_pending_revision() -> None:
    decoded = UserPolicyService._decode_mirror_event(_event())

    assert decoded == PendingUserPolicyMirrorEvent(
        event_id=7,
        source_revision=2,
        event_type="update",
        snapshot=SNAPSHOT,
        changed_fields=frozenset({"reform_label", "year"}),
        source_fingerprint_sha256=fingerprint_legacy_user_policy(SNAPSHOT),
    )


def test_valid_create_event_has_no_changed_fields() -> None:
    decoded = UserPolicyService._decode_mirror_event(
        _event(event_type="create", payload_json=_payload(changed_fields=[]))
    )

    assert decoded.event_type == "create"
    assert decoded.changed_fields == frozenset()


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"payload_schema_version": 2},
            "saved-policy mirror event payload version is unsupported",
        ),
        (
            {"payload_json": ["snapshot"]},
            "saved-policy mirror event payload has an invalid shape",
        ),
        (
            {"payload_json": {"snapshot": {}}},
            "saved-policy mirror event payload has an invalid shape",
        ),
        (
            {"payload_json": _payload(changed_fields="year")},
            "saved-policy mirror event changed fields are invalid",
        ),
        (
            {"payload_json": _payload(changed_fields=[1])},
            "saved-policy mirror event changed fields are invalid",
        ),
        (
            {"payload_json": _payload(changed_fields=["year", "reform_label"])},
            "saved-policy mirror event changed fields are unsupported",
        ),
        (
            {"payload_json": _payload(changed_fields=["year", "year"])},
            "saved-policy mirror event changed fields are unsupported",
        ),
        (
            {"payload_json": _payload(changed_fields=["user_id"])},
            "saved-policy mirror event changed fields are unsupported",
        ),
        (
            {"payload_json": _payload(snapshot={"country_id": "us"})},
            "saved-policy mirror event snapshot is invalid",
        ),
        (
            {"payload_json": _payload(snapshot=["us"])},
            "saved-policy mirror event snapshot is invalid",
        ),
        (
            {"country_id": "uk"},
            "saved-policy mirror event source identity conflicts with its payload",
        ),
        (
            {"legacy_user_policy_id": 11},
            "saved-policy mirror event source identity conflicts with its payload",
        ),
        (
            {"source_fingerprint_sha256": "f" * 64},
            "saved-policy mirror event fingerprint conflicts with its payload",
        ),
        ({"event_type": "delete"}, "saved-policy mirror event type is unsupported"),
        (
            {"event_type": "create"},
            "saved-policy create mirror event contains changed fields",
        ),
        (
            {"payload_json": _payload(changed_fields=[])},
            "saved-policy update mirror event has no changed fields",
        ),
    ],
)
def test_invalid_events_are_integrity_errors_with_specific_messages(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(UserPolicyMirrorEventIntegrityError, match=rf"^{message}$"):
        UserPolicyService._decode_mirror_event(_event(**changes))

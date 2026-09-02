"""Deterministic canonical policy-content tests."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from uuid import UUID, uuid4

from policyengine_api.services.v2.policies.canonicalization import (
    POLICY_CANONICALIZATION_VERSION,
    canonical_policy_document,
    canonicalize_policy,
)
from policyengine_api.services.v2.policies.commands import (
    ResolvedPolicyCreateCommand,
)


MODEL_ID = UUID("00000000-0000-0000-0000-000000000010")
MODEL_VERSION_ID = UUID("00000000-0000-0000-0000-000000000020")
FIRST_PARAMETER_ID = UUID("00000000-0000-0000-0000-000000000030")
SECOND_PARAMETER_ID = UUID("00000000-0000-0000-0000-000000000040")


def _command(*, values=None, **changes) -> ResolvedPolicyCreateCommand:
    fields = {
        "country_id": "us",
        "tax_benefit_model_id": MODEL_ID,
        "tax_benefit_model_version_id": MODEL_VERSION_ID,
        "policyengine_version": "5.2.0",
        "parameter_values": values
        if values is not None
        else [
            {
                "parameter_id": FIRST_PARAMETER_ID,
                "value": {"enabled": True, "rate": 1},
                "start_date": "2026-01-01T00:00:00Z",
            }
        ],
    }
    fields.update(changes)
    return ResolvedPolicyCreateCommand.model_validate(fields)


def test_document_has_versioned_deterministic_content_only() -> None:
    document = canonical_policy_document(_command())

    assert document == (
        b'{"canonicalization_version":1,"country_id":"us",'
        b'"parameter_values":[{"end_date":null,'
        b'"parameter_id":"00000000-0000-0000-0000-000000000030",'
        b'"start_date":"2026-01-01T00:00:00.000000Z",'
        b'"value":{"enabled":true,"rate":1}}],'
        b'"tax_benefit_model_id":"00000000-0000-0000-0000-000000000010",'
        b'"tax_benefit_model_version_id":'
        b'"00000000-0000-0000-0000-000000000020"}'
    )
    assert b"policyengine_version" not in document
    assert b"created_at" not in document
    assert b"name" not in document


def test_request_and_object_member_order_do_not_change_identity() -> None:
    first = {
        "parameter_id": FIRST_PARAMETER_ID,
        "value": {"z": [3, 2, 1], "a": {"right": 2, "left": 1}},
        "start_date": "2026-01-01T00:00:00Z",
    }
    second = {
        "parameter_id": SECOND_PARAMETER_ID,
        "value": "second",
        "start_date": "2027-01-01T00:00:00Z",
    }
    reordered_first = {
        **first,
        "value": {"a": {"left": 1, "right": 2}, "z": [3, 2, 1]},
    }

    assert canonicalize_policy(_command(values=[first, second])) == canonicalize_policy(
        _command(values=[second, reordered_first])
    )


def test_equivalent_json_numbers_and_utc_instants_have_one_encoding() -> None:
    integer = _command(
        values=[
            {
                "parameter_id": FIRST_PARAMETER_ID,
                "value": {"positive": 1, "zero": 0},
                "start_date": "2026-01-01T00:00:00Z",
            }
        ]
    )
    floating = _command(
        values=[
            {
                "parameter_id": FIRST_PARAMETER_ID,
                "value": {"zero": -0.0, "positive": 1.0},
                "start_date": "2026-01-01T03:00:00+03:00",
            }
        ]
    )

    assert canonicalize_policy(integer) == canonicalize_policy(floating)


def test_material_content_changes_produce_distinct_documents() -> None:
    original = canonical_policy_document(_command())
    alternatives = [
        _command(country_id="uk"),
        _command(tax_benefit_model_id=uuid4()),
        _command(tax_benefit_model_version_id=uuid4()),
        _command(
            values=[
                {
                    "parameter_id": SECOND_PARAMETER_ID,
                    "value": {"enabled": True, "rate": 1},
                    "start_date": "2026-01-01T00:00:00Z",
                }
            ]
        ),
        _command(
            values=[
                {
                    "parameter_id": FIRST_PARAMETER_ID,
                    "value": {"enabled": True, "rate": 2},
                    "start_date": "2026-01-01T00:00:00Z",
                }
            ]
        ),
        _command(
            values=[
                {
                    "parameter_id": FIRST_PARAMETER_ID,
                    "value": {"enabled": True, "rate": 1},
                    "start_date": "2026-01-02T00:00:00Z",
                }
            ]
        ),
        _command(
            values=[
                {
                    "parameter_id": FIRST_PARAMETER_ID,
                    "value": {"enabled": True, "rate": 1},
                    "start_date": "2026-01-01T00:00:00Z",
                    "end_date": "2026-12-31T00:00:00Z",
                }
            ]
        ),
    ]

    assert all(canonical_policy_document(item) != original for item in alternatives)


def test_digest_is_sha256_of_exact_canonical_bytes() -> None:
    content = canonicalize_policy(_command())

    assert content.version == POLICY_CANONICALIZATION_VERSION
    assert content.content_hash == hashlib.sha256(content.document).hexdigest()
    assert len(content.content_hash) == 64


def test_datetime_objects_are_rendered_at_fixed_microsecond_precision() -> None:
    command = _command(
        values=[
            {
                "parameter_id": FIRST_PARAMETER_ID,
                "value": 1,
                "start_date": datetime(
                    2026,
                    1,
                    1,
                    0,
                    0,
                    0,
                    42,
                    tzinfo=timezone.utc,
                ),
            }
        ]
    )
    assert b"2026-01-01T00:00:00.000042Z" in canonical_policy_document(command)

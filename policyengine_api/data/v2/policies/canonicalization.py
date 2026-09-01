"""Versioned canonical content identity for immutable v2 policies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any

from policyengine_api.services.v2.policies.commands import (
    ResolvedPolicyCreateCommand,
)


POLICY_CANONICALIZATION_VERSION = 1


@dataclass(frozen=True)
class CanonicalPolicyContent:
    """Canonical bytes and SHA-256 identity for one resolved policy."""

    version: int
    document: bytes
    content_hash: str


def _canonical_number(value: int | float) -> str:
    number = Decimal(str(value))
    if number.is_zero():
        return "0"
    rendered = format(number, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _canonical_json(value: Any) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) in {int, float}:
        return _canonical_number(value)
    if type(value) is str:
        return json.dumps(value, ensure_ascii=True, allow_nan=False)
    if type(value) is list:
        return "[" + ",".join(_canonical_json(item) for item in value) + "]"
    if type(value) is dict:
        members = (
            f"{json.dumps(key, ensure_ascii=True)}:{_canonical_json(value[key])}"
            for key in sorted(value)
        )
        return "{" + ",".join(members) + "}"
    raise TypeError("canonical policy content contains a non-JSON value")


def canonical_utc_datetime(value: datetime) -> str:
    """Render an aware datetime as fixed-width UTC with a trailing Z."""

    utc_value = value.astimezone(timezone.utc)
    return utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_policy_document(command: ResolvedPolicyCreateCommand) -> bytes:
    """Serialize only immutable policy content in deterministic order."""

    parameter_values = sorted(
        command.parameter_values,
        key=lambda value: (
            str(value.parameter_id),
            canonical_utc_datetime(value.start_date),
            "" if value.end_date is None else canonical_utc_datetime(value.end_date),
        ),
    )
    document = {
        "canonicalization_version": POLICY_CANONICALIZATION_VERSION,
        "country_id": command.country_id,
        "tax_benefit_model_id": str(command.tax_benefit_model_id),
        "tax_benefit_model_version_id": str(command.tax_benefit_model_version_id),
        "parameter_values": [
            {
                "parameter_id": str(value.parameter_id),
                "value": value.value,
                "start_date": canonical_utc_datetime(value.start_date),
                "end_date": (
                    None
                    if value.end_date is None
                    else canonical_utc_datetime(value.end_date)
                ),
            }
            for value in parameter_values
        ],
    }
    return _canonical_json(document).encode("ascii")


def canonicalize_policy(
    command: ResolvedPolicyCreateCommand,
) -> CanonicalPolicyContent:
    """Return versioned canonical bytes and their lowercase SHA-256 digest."""

    document = canonical_policy_document(command)
    return CanonicalPolicyContent(
        version=POLICY_CANONICALIZATION_VERSION,
        document=document,
        content_hash=hashlib.sha256(document).hexdigest(),
    )

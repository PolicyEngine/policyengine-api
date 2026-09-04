"""Pure representation transformations for v2 policy operations."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any
from uuid import UUID

from policyengine_core.periods import period as parse_policyengine_period  # type: ignore[import-untyped]

from policyengine_api.data.v2.catalog.catalog_selection import SelectedCatalog
from policyengine_api.data.v2.models import (
    Parameter,
    ParameterValue,
    Policy,
    TaxBenefitModelVersion,
)
from policyengine_api.services.v2.policies.types import (
    CanonicalPolicyContent,
    LegacyPolicySnapshot,
    PolicyCreationInput,
    PolicyPage,
    PolicyParameterValueInput,
    PolicyParameterValueRead,
    PolicyRead,
    ResolvedPolicyCreationInput,
)
from policyengine_api.services.v2.policies.validators import (
    LegacyPolicyTranslationError,
    validate_policy_catalog,
)


POLICY_CANONICALIZATION_VERSION = 1


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
    utc_value = value.astimezone(timezone.utc)
    return utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_policy_document(policy_input: ResolvedPolicyCreationInput) -> bytes:
    parameter_values = sorted(
        policy_input.parameter_values,
        key=lambda value: (
            str(value.parameter_id),
            canonical_utc_datetime(value.start_date),
            "" if value.end_date is None else canonical_utc_datetime(value.end_date),
        ),
    )
    document = {
        "canonicalization_version": POLICY_CANONICALIZATION_VERSION,
        "country_id": policy_input.country_id,
        "tax_benefit_model_id": str(policy_input.tax_benefit_model_id),
        "tax_benefit_model_version_id": str(policy_input.tax_benefit_model_version_id),
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
    policy_input: ResolvedPolicyCreationInput,
) -> CanonicalPolicyContent:
    document = canonical_policy_document(policy_input)
    return CanonicalPolicyContent(
        version=POLICY_CANONICALIZATION_VERSION,
        document=document,
        content_hash=hashlib.sha256(document).hexdigest(),
    )


def stored_policy_creation_input(
    policy: Policy,
    model_version: TaxBenefitModelVersion,
    values: list[ParameterValue],
) -> ResolvedPolicyCreationInput:
    return ResolvedPolicyCreationInput.model_validate(
        {
            "country_id": policy.country_id,
            "tax_benefit_model_id": policy.tax_benefit_model_id,
            "tax_benefit_model_version_id": policy.tax_benefit_model_version_id,
            "policyengine_version": model_version.version,
            "parameter_values": [
                {
                    "parameter_id": value.parameter_id,
                    "value": value.value_json,
                    "start_date": value.start_date,
                    "end_date": value.end_date,
                }
                for value in values
            ],
        }
    )


def policy_parameter_values_by_policy(
    policy_ids: list[UUID],
    rows: list[tuple[ParameterValue, str]],
) -> dict[UUID, tuple[PolicyParameterValueRead, ...]]:
    grouped: dict[UUID, list[PolicyParameterValueRead]] = {
        policy_id: [] for policy_id in policy_ids
    }
    for value, parameter_name in rows:
        if value.policy_id is None:
            continue
        grouped[value.policy_id].append(
            PolicyParameterValueRead(
                id=value.id,
                parameter_id=value.parameter_id,
                parameter_name=parameter_name,
                value=value.value_json,
                start_date=value.start_date,
                end_date=value.end_date,
            )
        )
    return {policy_id: tuple(values) for policy_id, values in grouped.items()}


def policy_read(
    policy: Policy,
    values: dict[UUID, tuple[PolicyParameterValueRead, ...]],
) -> PolicyRead:
    return PolicyRead(
        id=policy.id,
        country_id=policy.country_id,
        tax_benefit_model_id=policy.tax_benefit_model_id,
        tax_benefit_model_version_id=policy.tax_benefit_model_version_id,
        created_at=policy.created_at,
        updated_at=policy.updated_at,
        parameter_values=values.get(policy.id, ()),
    )


def policy_page(
    rows: list[Policy],
    values: dict[UUID, tuple[PolicyParameterValueRead, ...]],
    *,
    offset: int,
    limit: int,
) -> PolicyPage:
    policies = rows[:limit]
    return PolicyPage(
        items=tuple(policy_read(policy, values) for policy in policies),
        offset=offset,
        limit=limit,
        has_more=len(rows) > limit,
    )


def _utc_midnight(value: str) -> datetime:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise LegacyPolicyTranslationError(
            f"legacy period {value!r} is invalid"
        ) from error
    return datetime.combine(parsed, time.min, tzinfo=timezone.utc)


def parse_legacy_period(value: str) -> tuple[datetime, datetime]:
    if not value or value != value.strip():
        raise LegacyPolicyTranslationError("legacy period must be non-empty")
    if "." in value:
        parts = value.split(".")
        if len(parts) != 2:
            raise LegacyPolicyTranslationError(
                f"legacy period {value!r} must contain one date range"
            )
        start_date, end_date = (_utc_midnight(item) for item in parts)
    else:
        try:
            parsed = parse_policyengine_period(value)
            start_date = _utc_midnight(str(parsed.start))
            end_date = _utc_midnight(str(parsed.stop))
        except (TypeError, ValueError) as error:
            raise LegacyPolicyTranslationError(
                f"legacy period {value!r} is invalid"
            ) from error
    if end_date < start_date:
        raise LegacyPolicyTranslationError(
            f"legacy period {value!r} ends before it starts"
        )
    return start_date, end_date


def translate_legacy_policy(
    snapshot: LegacyPolicySnapshot,
    *,
    selected: SelectedCatalog,
    parameters: Mapping[str, Parameter],
    country_package_versions: Mapping[str, str],
) -> ResolvedPolicyCreationInput:
    expected_api_version = country_package_versions.get(snapshot.country_id)
    if expected_api_version is None or snapshot.api_version != expected_api_version:
        raise LegacyPolicyTranslationError(
            "legacy policy api_version does not match the running country package"
        )
    policy_json = snapshot.policy_json
    assert isinstance(policy_json, dict)
    parameter_names = set(policy_json)
    if set(parameters) != parameter_names:
        raise LegacyPolicyTranslationError(
            "every legacy parameter path must exist in the running catalog"
        )

    parameter_values: list[PolicyParameterValueInput] = []
    for parameter_name in sorted(parameter_names):
        period_values = policy_json[parameter_name]
        if type(period_values) is not dict:
            raise LegacyPolicyTranslationError(
                f"legacy parameter {parameter_name!r} must contain period/value entries"
            )
        for period_name, value in sorted(period_values.items()):
            if type(period_name) is not str:
                raise LegacyPolicyTranslationError(
                    f"legacy parameter {parameter_name!r} has a non-string period"
                )
            start_date, end_date = parse_legacy_period(period_name)
            parameter_values.append(
                PolicyParameterValueInput(
                    parameter_id=parameters[parameter_name].id,
                    value=value,
                    start_date=start_date,
                    end_date=end_date,
                )
            )
    try:
        policy_input = PolicyCreationInput(
            country_id=snapshot.country_id,
            tax_benefit_model_id=selected.model.id,
            parameter_values=parameter_values,
        )
    except ValueError as error:
        raise LegacyPolicyTranslationError(
            "legacy parameter periods or values conflict"
        ) from error
    return validate_policy_catalog(
        policy_input,
        selected=selected,
        resolved_parameter_ids={parameter.id for parameter in parameters.values()},
    )

"""Translation of committed v1 policy snapshots into v2 policy commands."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Annotated
from uuid import UUID

from policyengine_core.periods import period as parse_policyengine_period
from pydantic import Field, field_validator
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, select

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS, POLICYENGINE_VERSION
from policyengine_api.data.v2.catalog.catalog_selection import select_catalog
from policyengine_api.data.v2.models import LegacyPolicyMapping, Parameter
from policyengine_api.data.v2.policies.catalog import resolve_policy_catalog
from policyengine_api.data.v2.policies.persistence import persist_resolved_policy
from policyengine_api.data.v2.policies.schemas import (
    PolicyCreateCommand,
    ResolvedPolicyCreateCommand,
    StrictJsonValue,
    StrictPolicyCommand,
)
from policyengine_api.query_parameters import CountryId


class LegacyPolicyTranslationError(ValueError):
    """Raised when committed v1 content cannot be interpreted exactly."""


class LegacyPolicyMappingIntegrityError(RuntimeError):
    """Raised when one immutable v1 identity changes or maps inconsistently."""


@dataclass(frozen=True)
class LegacyPolicyPersistenceResult:
    """Destination identity and insertion outcomes for one mirror attempt."""

    policy_id: UUID
    policy_created: bool
    mapping_created: bool


class LegacyPolicySnapshot(StrictPolicyCommand):
    """Detached committed fields required by the v2 policy mirror."""

    country_id: CountryId
    legacy_policy_id: Annotated[int, Field(ge=0)]
    label: Annotated[str, Field(max_length=255)] | None = None
    api_version: Annotated[str, Field(min_length=1, max_length=255)]
    policy_json: StrictJsonValue
    source_policy_hash: Annotated[str, Field(min_length=1, max_length=255)]

    @field_validator("policy_json")
    @classmethod
    def require_parameter_mapping(cls, value: object) -> object:
        if type(value) is not dict:
            raise ValueError("legacy policy_json must be a parameter-path object")
        return value


def _utc_midnight(value: str) -> datetime:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise LegacyPolicyTranslationError(
            f"legacy period date {value!r} is invalid"
        ) from error
    return datetime.combine(parsed, time.min, tzinfo=timezone.utc)


def parse_legacy_period(value: str) -> tuple[datetime, datetime]:
    """Translate one legacy period key to inclusive UTC endpoints."""

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


def _parameters_by_name(
    session: Session,
    *,
    model_version_id,
    names: set[str],
) -> dict[str, Parameter]:
    if not names:
        return {}
    parameters = session.exec(
        select(Parameter).where(
            Parameter.tax_benefit_model_version_id == model_version_id,
            Parameter.name.in_(names),
        )
    ).all()
    return {parameter.name: parameter for parameter in parameters}


def translate_legacy_policy(
    session: Session,
    snapshot: LegacyPolicySnapshot,
    *,
    running_policyengine_version: str = POLICYENGINE_VERSION,
    country_package_versions: Mapping[str, str] = COUNTRY_PACKAGE_VERSIONS,
) -> ResolvedPolicyCreateCommand:
    """Resolve a committed legacy reform through the exact running catalog."""

    expected_api_version = country_package_versions.get(snapshot.country_id)
    if expected_api_version is None or snapshot.api_version != expected_api_version:
        raise LegacyPolicyTranslationError(
            "legacy policy api_version does not match the running country package"
        )
    selected = select_catalog(
        session,
        country_id=snapshot.country_id,
        running_policyengine_version=running_policyengine_version,
    )
    policy_json = snapshot.policy_json
    assert isinstance(policy_json, dict)
    parameter_names = set(policy_json)
    parameters = _parameters_by_name(
        session,
        model_version_id=selected.model_version.id,
        names=parameter_names,
    )
    if set(parameters) != parameter_names:
        raise LegacyPolicyTranslationError(
            "every legacy parameter path must exist in the running catalog"
        )

    parameter_values: list[dict[str, object]] = []
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
                {
                    "parameter_id": parameters[parameter_name].id,
                    "value": value,
                    "start_date": start_date,
                    "end_date": end_date,
                }
            )

    try:
        command = PolicyCreateCommand(
            country_id=snapshot.country_id,
            tax_benefit_model_id=selected.model.id,
            parameter_values=parameter_values,
        )
    except ValueError as error:
        raise LegacyPolicyTranslationError(
            "legacy parameter periods or values conflict"
        ) from error
    return resolve_policy_catalog(
        session,
        command,
        running_policyengine_version=running_policyengine_version,
    )


def _legacy_mapping(
    session: Session,
    snapshot: LegacyPolicySnapshot,
    *,
    lock: bool,
) -> LegacyPolicyMapping | None:
    statement = select(LegacyPolicyMapping).where(
        LegacyPolicyMapping.country_id == snapshot.country_id,
        LegacyPolicyMapping.legacy_policy_id == snapshot.legacy_policy_id,
    )
    if lock:
        statement = statement.with_for_update()
    return session.exec(statement).one_or_none()


def _verify_legacy_mapping(
    mapping: LegacyPolicyMapping,
    snapshot: LegacyPolicySnapshot,
    *,
    expected_policy_id: UUID | None = None,
) -> None:
    if mapping.source_policy_hash != snapshot.source_policy_hash:
        raise LegacyPolicyMappingIntegrityError(
            "legacy policy identity was presented with a different source hash"
        )
    if expected_policy_id is not None and mapping.policy_id != expected_policy_id:
        raise LegacyPolicyMappingIntegrityError(
            "legacy policy mapping does not match translated immutable content"
        )


def persist_legacy_policy(
    session: Session,
    snapshot: LegacyPolicySnapshot,
    *,
    running_policyengine_version: str = POLICYENGINE_VERSION,
    country_package_versions: Mapping[str, str] = COUNTRY_PACKAGE_VERSIONS,
) -> LegacyPolicyPersistenceResult:
    """Translate, deduplicate, and map one v1 policy in the caller transaction."""

    existing = _legacy_mapping(session, snapshot, lock=True)
    if existing is not None:
        _verify_legacy_mapping(existing, snapshot)

    command = translate_legacy_policy(
        session,
        snapshot,
        running_policyengine_version=running_policyengine_version,
        country_package_versions=country_package_versions,
    )
    policy_result = persist_resolved_policy(session, command)
    if existing is not None:
        _verify_legacy_mapping(
            existing,
            snapshot,
            expected_policy_id=policy_result.policy_id,
        )
        return LegacyPolicyPersistenceResult(
            policy_id=existing.policy_id,
            policy_created=False,
            mapping_created=False,
        )

    mapping_id = session.execute(
        insert(LegacyPolicyMapping)
        .values(
            country_id=snapshot.country_id,
            legacy_policy_id=snapshot.legacy_policy_id,
            policy_id=policy_result.policy_id,
            source_policy_hash=snapshot.source_policy_hash,
        )
        .on_conflict_do_nothing(constraint="uq_legacy_policy_mappings_country_legacy")
        .returning(LegacyPolicyMapping.id)
    ).scalar_one_or_none()
    if mapping_id is not None:
        return LegacyPolicyPersistenceResult(
            policy_id=policy_result.policy_id,
            policy_created=policy_result.created,
            mapping_created=True,
        )

    concurrent = _legacy_mapping(session, snapshot, lock=False)
    if concurrent is None:
        raise LegacyPolicyMappingIntegrityError(
            "legacy policy mapping conflict did not resolve to a stored row"
        )
    _verify_legacy_mapping(
        concurrent,
        snapshot,
        expected_policy_id=policy_result.policy_id,
    )
    return LegacyPolicyPersistenceResult(
        policy_id=concurrent.policy_id,
        policy_created=False,
        mapping_created=False,
    )

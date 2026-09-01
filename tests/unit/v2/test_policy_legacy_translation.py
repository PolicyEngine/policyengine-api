"""Legacy policy snapshot and translation tests."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import ValidationError
from sqlmodel import Session, create_engine
import pytest

from policyengine_api.data.v2.models import (
    Parameter,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    V2_METADATA,
)
from policyengine_api.data.v2.policies.legacy import (
    LegacyPolicySnapshot,
    LegacyPolicyTranslationError,
    parse_legacy_period,
    translate_legacy_policy,
)


def _session_and_catalog():
    engine = create_engine("sqlite://")
    V2_METADATA.create_all(engine)
    session = Session(engine)
    model = TaxBenefitModel(name="policyengine-us")
    version = TaxBenefitModelVersion(
        model=model,
        version="5.2.0",
        current_law_id=1,
        metadata_time_periods=[2026],
    )
    first = Parameter(
        name="gov.example.rate",
        tax_benefit_model_version=version,
    )
    second = Parameter(
        name="gov.example.amount",
        tax_benefit_model_version=version,
    )
    session.add_all([first, second])
    session.commit()
    return engine, session, model, version, first, second


def _snapshot(**changes) -> LegacyPolicySnapshot:
    fields = {
        "country_id": "us",
        "legacy_policy_id": 42,
        "label": "Presentation only",
        "api_version": "1.0.0",
        "policy_json": {
            "gov.example.rate": {"2026": 0.2},
            "gov.example.amount": {"2026-01-01.2026-12-31": 100},
        },
        "source_policy_hash": "legacy/base64+hash=",
    }
    fields.update(changes)
    return LegacyPolicySnapshot.model_validate(fields)


def test_year_day_and_explicit_range_periods_are_inclusive_utc() -> None:
    assert parse_legacy_period("2026") == (
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 12, 31, tzinfo=timezone.utc),
    )
    assert parse_legacy_period("2026-03-02") == (
        datetime(2026, 3, 2, tzinfo=timezone.utc),
        datetime(2026, 3, 2, tzinfo=timezone.utc),
    )
    assert parse_legacy_period("2026-02-01.2026-02-28") == (
        datetime(2026, 2, 1, tzinfo=timezone.utc),
        datetime(2026, 2, 28, tzinfo=timezone.utc),
    )


def test_translation_resolves_paths_and_excludes_legacy_identity_and_label() -> None:
    engine, session, model, version, first, second = _session_and_catalog()
    try:
        translated = translate_legacy_policy(
            session,
            _snapshot(),
            running_policyengine_version="5.2.0",
            country_package_versions={"us": "1.0.0"},
        )

        assert translated.tax_benefit_model_id == model.id
        assert translated.tax_benefit_model_version_id == version.id
        assert {value.parameter_id for value in translated.parameter_values} == {
            first.id,
            second.id,
        }
        assert "label" not in type(translated).model_fields
        assert "legacy_policy_id" not in type(translated).model_fields
    finally:
        session.close()
        engine.dispose()


def test_label_does_not_change_translated_core_content() -> None:
    engine, session, _model, _version, _first, _second = _session_and_catalog()
    try:
        first = translate_legacy_policy(
            session,
            _snapshot(label="First"),
            running_policyengine_version="5.2.0",
            country_package_versions={"us": "1.0.0"},
        )
        second = translate_legacy_policy(
            session,
            _snapshot(label="Second", legacy_policy_id=43),
            running_policyengine_version="5.2.0",
            country_package_versions={"us": "1.0.0"},
        )
        assert first == second
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize(
    "policy_json",
    [
        {"gov.missing": {"2026": 1}},
        {"gov.example.rate": 1},
        {"gov.example.rate": {"not-a-period": 1}},
        {
            "gov.example.rate": {
                "2026": 1,
                "2026-01-01.2026-12-31": 2,
            }
        },
    ],
)
def test_missing_paths_malformed_periods_and_conflicts_fail(
    policy_json: dict[str, object],
) -> None:
    engine, session, _model, _version, _first, _second = _session_and_catalog()
    try:
        with pytest.raises(LegacyPolicyTranslationError):
            translate_legacy_policy(
                session,
                _snapshot(policy_json=policy_json),
                running_policyengine_version="5.2.0",
                country_package_versions={"us": "1.0.0"},
            )
    finally:
        session.close()
        engine.dispose()


def test_country_package_version_must_match_running_release() -> None:
    engine, session, _model, _version, _first, _second = _session_and_catalog()
    try:
        with pytest.raises(LegacyPolicyTranslationError, match="api_version"):
            translate_legacy_policy(
                session,
                _snapshot(api_version="0.9.0"),
                running_policyengine_version="5.2.0",
                country_package_versions={"us": "1.0.0"},
            )
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize(
    "changes",
    [
        {"policy_json": ["not", "an", "object"]},
        {"source_policy_hash": ""},
        {"legacy_policy_id": -1},
        {"policy_json": {"gov.example": {"2026": float("nan")}}},
    ],
)
def test_snapshot_rejects_incomplete_or_non_json_committed_fields(changes) -> None:
    with pytest.raises(ValidationError):
        _snapshot(**changes)


def test_reverse_legacy_range_is_rejected() -> None:
    with pytest.raises(LegacyPolicyTranslationError, match="ends before"):
        parse_legacy_period("2026-12-31.2026-01-01")


def test_unknown_policyengine_version_never_falls_back() -> None:
    engine, session, _model, _version, _first, _second = _session_and_catalog()
    try:
        with pytest.raises(Exception, match="running PolicyEngine.py"):
            translate_legacy_policy(
                session,
                _snapshot(),
                running_policyengine_version="4.0.0",
                country_package_versions={"us": "1.0.0"},
            )
    finally:
        session.close()
        engine.dispose()

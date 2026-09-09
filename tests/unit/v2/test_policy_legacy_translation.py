"""Legacy policy snapshot and translation tests."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from pydantic import ValidationError
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, create_engine
import pytest

from policyengine_api.data.v2.models import (
    Parameter,
    TaxBenefitModel,
    TaxBenefitModelVersion,
    V2_METADATA,
)
from policyengine_api.services.v2.policies.database_connectors.reads import (
    read_parameters_by_name,
    read_policy_catalog,
)
from policyengine_api.services.v2.policies.transformations import (
    canonicalize_policy,
    parse_legacy_period,
    translate_legacy_policy,
)
from policyengine_api.services.v2.policies.types import LegacyPolicySnapshot
from policyengine_api.services.v2.policies.validators import (
    LegacyPolicyTranslationError,
)
from policyengine_api.services.policy_service import PolicyService
from policyengine_api.services.policy_mirroring import (
    PolicyMirrorUnavailableError,
    mirror_policy_after_commit,
)
from tests.fixtures.local_v1_database import create_test_v1_schema


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


def _translate(
    session: Session,
    snapshot: LegacyPolicySnapshot,
    *,
    running_policyengine_version: str = "5.2.0",
):
    selected = read_policy_catalog(
        session,
        snapshot.country_id,
        running_policyengine_version=running_policyengine_version,
    )
    assert isinstance(snapshot.policy_json, dict)
    parameters = read_parameters_by_name(
        session,
        model_version_id=selected.model_version.id,
        names=set(snapshot.policy_json),
    )
    return translate_legacy_policy(
        snapshot,
        selected=selected,
        parameters=parameters,
        country_package_versions={"us": "1.0.0"},
    )


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
        translated = _translate(session, _snapshot())

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
        first = _translate(session, _snapshot(label="First"))
        second = _translate(session, _snapshot(label="Second", legacy_policy_id=43))
        assert first == second
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("request_value", "stored_value"),
    [
        (0.04 + 3 / 1_000_000, 0.040003),
        (1.4334335999999999, 1.4334336),
        (-5.684341886080803e-14, -5.684341886080804e-14),
    ],
)
def test_new_retry_and_equivalent_label_mirror_the_same_stored_json(
    monkeypatch, request_value: float, stored_value: float
) -> None:
    # MySQL's default RapidJSON parser can move a double by one ULP:
    # https://bugs.mysql.com/bug.php?id=112904
    # The first pair also comes from the live Phase 10 probe's value formula.
    # Model those specific storage round trips at the database boundary. Plain
    # SQLite JSON would preserve the request float and hide this regression.
    def serialize_stored_json(value):
        return json.dumps(
            json.loads(
                json.dumps(value),
                parse_float=lambda number: (
                    stored_value if number == repr(request_value) else float(number)
                ),
            )
        )

    v1_engine = create_engine("sqlite://", json_serializer=serialize_stored_json)
    create_test_v1_schema(v1_engine)
    service = PolicyService(sessionmaker(v1_engine, expire_on_commit=False))
    monkeypatch.setattr(
        "policyengine_api.services.policy_service.COUNTRY_PACKAGE_VERSIONS",
        {"us": "1.0.0"},
    )
    engine, session, _model, _version, _first, _second = _session_and_catalog()
    request = {
        "gov.example.rate": {"2026-01-01.2100-12-31": request_value},
        "gov.example.amount": {"2026": 100},
    }
    try:
        first = service.set_policy(
            "us", "First label", request, prepare_for_mirroring=True
        )

        def unavailable_mirror():
            raise RuntimeError("controlled destination failure")

        with pytest.raises(PolicyMirrorUnavailableError):
            mirror_policy_after_commit(
                first.snapshot, mirror_factory=unavailable_mirror
            )
        assert service.get_policy("us", first.policy_id) is not None
        # Retry loads the committed row; the equivalent-label request creates
        # a different legacy row.
        retry = service.set_policy(
            "us", "First label", request, prepare_for_mirroring=True
        )
        equivalent = service.set_policy(
            "us", "Equivalent label", request, prepare_for_mirroring=True
        )
        assert first.is_existing_policy is False
        assert retry.is_existing_policy is True
        assert equivalent.is_existing_policy is False
        assert retry.policy_id == first.policy_id
        assert equivalent.policy_id != first.policy_id
        assert equivalent.snapshot.label != first.snapshot.label
        assert (
            equivalent.snapshot.source_policy_hash == first.snapshot.source_policy_hash
        )
        contents = [
            canonicalize_policy(_translate(session, result.snapshot))
            for result in (first, retry, equivalent)
        ]
        assert contents[2] == contents[1]
        assert contents[0] == contents[1]
        stored = service.get_policy_snapshot("us", first.policy_id)
        assert stored.policy_json["gov.example.rate"] == {
            "2026-01-01.2100-12-31": stored_value
        }
        assert all(
            result.snapshot.policy_json == stored.policy_json
            for result in (first, retry, equivalent)
        )
        assert request["gov.example.rate"]["2026-01-01.2100-12-31"] == request_value
    finally:
        session.close()
        engine.dispose()
        v1_engine.dispose()


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
            _translate(session, _snapshot(policy_json=policy_json))
    finally:
        session.close()
        engine.dispose()


def test_country_package_version_must_match_running_release() -> None:
    engine, session, _model, _version, _first, _second = _session_and_catalog()
    try:
        with pytest.raises(LegacyPolicyTranslationError, match="api_version"):
            _translate(session, _snapshot(api_version="0.9.0"))
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
            _translate(
                session,
                _snapshot(),
                running_policyengine_version="4.0.0",
            )
    finally:
        session.close()
        engine.dispose()

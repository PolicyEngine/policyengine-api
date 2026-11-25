"""Legacy policy snapshot and translation tests."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from policyengine_api.data.v2.catalog.catalog_selection_validation import (
    MetadataCatalogNotPublishedError,
)
from policyengine_api.data.v2.models import (
    Parameter,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.services.policy_mirroring import (
    PolicyMirrorUnavailableError,
    mirror_policy_after_commit,
)
from policyengine_api.services.policy_service import PolicyService
from policyengine_api.services.v2.policies.database_connectors.reads import (
    read_parameters_by_name,
    read_policy_catalog,
)
from policyengine_api.services.v2.policies.transformations import (
    canonicalize_policy,
    parse_legacy_period,
    translate_legacy_policy,
)
from policyengine_api.services.v2.policies.types import (
    LegacyPolicySnapshot,
    LegacyPolicyTranslationReason,
)
from policyengine_api.services.v2.policies.validators import (
    MAXIMUM_POLICY_PARAMETER_VALUES,
    LegacyPolicyTranslationError,
    parameters_missing_from_model,
)
from tests.fixtures.database_sessions import sqlite_v1_sessions, sqlite_v2_sessions

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlmodel import Session


@contextmanager
def _session_and_catalog() -> Iterator[
    tuple[Session, TaxBenefitModel, TaxBenefitModelVersion, Parameter, Parameter]
]:
    """Yield a Session of a catalog version with two parameters, and the catalog."""
    with sqlite_v2_sessions() as sessions, sessions(expire_on_commit=True) as session:
        yield (session, *_store_catalog(session))


def _store_catalog(
    session: Session,
) -> tuple[TaxBenefitModel, TaxBenefitModelVersion, Parameter, Parameter]:
    """Store a model's catalog version with two parameters; return them."""
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
    return model, version, first, second


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
    ).policy


def test_year_day_and_explicit_range_periods_are_inclusive_utc() -> None:
    assert parse_legacy_period("2026") == (
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 12, 31, tzinfo=UTC),
    )
    assert parse_legacy_period("2026-03-02") == (
        datetime(2026, 3, 2, tzinfo=UTC),
        datetime(2026, 3, 2, tzinfo=UTC),
    )
    assert parse_legacy_period("2026-02-01.2026-02-28") == (
        datetime(2026, 2, 1, tzinfo=UTC),
        datetime(2026, 2, 28, tzinfo=UTC),
    )


def test_translation_resolves_paths_and_excludes_legacy_identity_and_label() -> None:
    with _session_and_catalog() as (session, model, version, first, second):
        translated = _translate(session, _snapshot())

        assert translated.tax_benefit_model_id == model.id
        assert translated.tax_benefit_model_version_id == version.id
        assert {value.parameter_id for value in translated.parameter_values} == {
            first.id,
            second.id,
        }
        assert "label" not in type(translated).model_fields
        assert "legacy_policy_id" not in type(translated).model_fields


def test_label_does_not_change_translated_core_content() -> None:
    with _session_and_catalog() as (session, _model, _version, _first, _second):
        first = _translate(session, _snapshot(label="First"))
        second = _translate(session, _snapshot(label="Second", legacy_policy_id=43))
        assert first == second


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

    monkeypatch.setattr(
        "policyengine_api.services.policy_service.COUNTRY_PACKAGE_VERSIONS",
        {"us": "1.0.0"},
    )
    request = {
        "gov.example.rate": {"2026-01-01.2100-12-31": request_value},
        "gov.example.amount": {"2026": 100},
    }
    with (
        sqlite_v1_sessions(json_serializer=serialize_stored_json) as v1_sessions,
        _session_and_catalog() as (session, _model, _version, _first, _second),
    ):
        service = PolicyService(v1_sessions)
        first = service.set_policy(
            "us", "First label", request, prepare_for_mirroring=True
        )

        def unavailable_mirror():
            msg = "controlled destination failure"
            raise RuntimeError(msg)

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


@pytest.mark.parametrize(
    ("policy_json", "reason"),
    [
        pytest.param(
            {"gov.missing": {"2026": 1}},
            LegacyPolicyTranslationReason.MISSING_PARAMETERS,
            id="unknown-path",
        ),
        pytest.param(
            {"gov.example.rate": {"2026": 1}, "gov.removed": {"2026": 2}},
            LegacyPolicyTranslationReason.MISSING_PARAMETERS,
            id="one-of-two-paths-unknown",
        ),
        pytest.param(
            {"gov.example.rate": 1},
            LegacyPolicyTranslationReason.INVALID_PARAMETER_VALUES,
            id="value-without-period",
        ),
        pytest.param(
            {"gov.example.rate": {}},
            LegacyPolicyTranslationReason.EMPTY_PARAMETER_VALUES,
            id="empty-period-object",
        ),
        pytest.param(
            {"gov.example.rate": {"not-a-period": 1}},
            LegacyPolicyTranslationReason.INVALID_PERIOD,
            id="unparseable-period",
        ),
        pytest.param(
            {"gov.example.rate": {".": 1}},
            LegacyPolicyTranslationReason.INVALID_PERIOD,
            id="dot-period",
        ),
        pytest.param(
            {
                "gov.example.rate": {
                    "2026": 1,
                    "2026-01-01.2026-12-31": 2,
                }
            },
            LegacyPolicyTranslationReason.CONFLICTING_VALUES,
            id="two-values-same-start",
        ),
    ],
)
def test_untranslatable_policy_fails_with_a_fixed_reason(
    policy_json: dict[str, object],
    reason: LegacyPolicyTranslationReason,
) -> None:
    with _session_and_catalog() as (session, _model, _version, _first, _second):
        with pytest.raises(LegacyPolicyTranslationError) as failure:
            _translate(session, _snapshot(policy_json=policy_json))
        assert failure.value.reason is reason


def test_policy_with_more_values_than_v2_accepts_fails_as_too_many_values() -> None:
    # One more dated value than a v2 policy may hold, with no repeated dates.
    too_many_periods = {
        f"{2026 + offset}-01-01.{2026 + offset}-12-31": offset
        for offset in range(MAXIMUM_POLICY_PARAMETER_VALUES + 1)
    }
    with _session_and_catalog() as (session, _model, _version, _first, _second):
        with pytest.raises(LegacyPolicyTranslationError) as failure:
            _translate(
                session,
                _snapshot(policy_json={"gov.example.rate": too_many_periods}),
            )
        assert failure.value.reason is LegacyPolicyTranslationReason.TOO_MANY_VALUES


def test_parameters_missing_from_model_lists_each_absent_name_once_in_order() -> None:
    model_parameter_names = {"gov.example.rate", "gov.example.amount"}

    assert parameters_missing_from_model(
        ["gov.removed.b", "gov.example.rate", "gov.removed.a", "gov.removed.b"],
        model_parameter_names,
    ) == ("gov.removed.a", "gov.removed.b")
    assert parameters_missing_from_model([], model_parameter_names) == ()
    assert (
        parameters_missing_from_model(
            {"gov.example.amount": {"2026": 1}}, model_parameter_names
        )
        == ()
    )


@pytest.mark.parametrize("saved_api_version", ["0.9.0", "1.633.2", "99.0.0"])
def test_policy_saved_under_another_country_package_translates_to_running_catalog(
    saved_api_version: str,
) -> None:
    with _session_and_catalog() as (session, _model, version, first, second):
        translated = _translate(session, _snapshot(api_version=saved_api_version))

        assert translated.tax_benefit_model_version_id == version.id
        assert {value.parameter_id for value in translated.parameter_values} == {
            first.id,
            second.id,
        }
        assert translated == _translate(session, _snapshot())


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
    with pytest.raises(LegacyPolicyTranslationError, match="ends before") as failure:
        parse_legacy_period("2026-12-31.2026-01-01")
    assert failure.value.reason is LegacyPolicyTranslationReason.INVALID_PERIOD


def test_unknown_policyengine_version_never_falls_back() -> None:
    with (
        _session_and_catalog() as (session, _model, _version, _first, _second),
        pytest.raises(
            MetadataCatalogNotPublishedError, match=r"running PolicyEngine\.py"
        ),
    ):
        _translate(
            session,
            _snapshot(),
            running_policyengine_version="4.0.0",
        )

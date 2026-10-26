"""Copy committed v1 policies into v2 with the running catalog.

The catalog and mapping reads run against SQLite. The two inserts use
PostgreSQL's ON CONFLICT ON CONSTRAINT, so the tests record them instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlmodel import Session, create_engine

from policyengine_api.data.v2.models import (
    V2_METADATA,
    LegacyPolicyMapping,
    Parameter,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.services.v2.policies import services as policy_services
from policyengine_api.services.v2.policies.types import (
    LegacyPolicyPersistenceResult,
    LegacyPolicySnapshot,
    PolicyCreationResult,
    ResolvedPolicyCreationInput,
)
from policyengine_api.services.v2.policies.validators import (
    LegacyPolicyMappingIntegrityError,
)

RUNNING_POLICYENGINE_VERSION = "6.7.5"
COPIED_POLICY_ID = UUID("00000000-0000-0000-0000-000000000042")
EARLIER_COPY_POLICY_ID = UUID("00000000-0000-0000-0000-000000000041")
MAPPING_ID = UUID("00000000-0000-0000-0000-000000000043")


@dataclass
class RecordedCopyWrites:
    """The policies and mappings a copy would have inserted, in order."""

    created_policies: list[ResolvedPolicyCreationInput] = field(default_factory=list)
    created_mappings: list[dict[str, object]] = field(default_factory=list)


@pytest.fixture
def recorded_writes(monkeypatch) -> RecordedCopyWrites:
    writes = RecordedCopyWrites()

    def record_policy(_session, policy_input):
        writes.created_policies.append(policy_input)
        return PolicyCreationResult(policy_id=COPIED_POLICY_ID, created=True)

    def record_mapping(_session, **mapping_fields):
        writes.created_mappings.append(mapping_fields)
        return MAPPING_ID

    monkeypatch.setattr(policy_services, "create_resolved_policy", record_policy)
    monkeypatch.setattr(policy_services, "create_legacy_policy_mapping", record_mapping)
    return writes


@pytest.fixture
def catalog_session():
    engine = create_engine("sqlite://")
    V2_METADATA.create_all(engine)
    session = Session(engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _add_running_catalog(
    session: Session, *, country_id: str, parameter_names: list[str]
) -> tuple[TaxBenefitModelVersion, dict[str, Parameter]]:
    model = TaxBenefitModel(name=f"policyengine-{country_id}")
    version = TaxBenefitModelVersion(
        model=model,
        version=RUNNING_POLICYENGINE_VERSION,
        current_law_id=1,
        metadata_time_periods=[2026],
    )
    parameters = {
        name: Parameter(name=name, tax_benefit_model_version=version)
        for name in parameter_names
    }
    session.add(version)
    session.add_all(parameters.values())
    session.commit()
    return version, parameters


def _snapshot(
    *,
    country_id: str,
    legacy_policy_id: int,
    api_version: str,
    policy_json: dict[str, object],
) -> LegacyPolicySnapshot:
    return LegacyPolicySnapshot(
        country_id=country_id,
        legacy_policy_id=legacy_policy_id,
        label=None,
        api_version=api_version,
        policy_json=policy_json,
        source_policy_hash=f"legacy-hash-{legacy_policy_id}",
    )


def _copy(session: Session, snapshot: LegacyPolicySnapshot):
    return policy_services.mirror_legacy_policy_in_session(
        session,
        snapshot,
        running_policyengine_version=RUNNING_POLICYENGINE_VERSION,
    )


@dataclass(frozen=True)
class ReusedProductionPolicy:
    """The shape of a v1 policy whose production copy failed."""

    country_id: str
    legacy_policy_id: int
    saved_api_version: str
    parameter_name: str
    value: float


# The two production copies that failed after dual-write was turned on: each
# POST matched an existing v1 row saved under a country package release many
# versions older than the one the Public API ran (us 2.2.1, uk 2.130.1).
PRODUCTION_REUSED_POLICIES = [
    pytest.param(
        ReusedProductionPolicy("us", 96567, "1.633.2", "gov.dol.minimum_wage", 9),
        id="us-96567-saved-under-1.633.2",
    ),
    pytest.param(
        ReusedProductionPolicy("uk", 97839, "2.89.2", "gov.boe.base_rate", 0.05),
        id="uk-97839-saved-under-2.89.2",
    ),
]


@pytest.mark.parametrize("reused_policy", PRODUCTION_REUSED_POLICIES)
def test_policy_saved_under_an_older_country_package_is_copied(
    catalog_session: Session,
    recorded_writes: RecordedCopyWrites,
    reused_policy: ReusedProductionPolicy,
) -> None:
    country_id = reused_policy.country_id
    parameter_name = reused_policy.parameter_name
    version, parameters = _add_running_catalog(
        catalog_session, country_id=country_id, parameter_names=[parameter_name]
    )
    snapshot = _snapshot(
        country_id=country_id,
        legacy_policy_id=reused_policy.legacy_policy_id,
        api_version=reused_policy.saved_api_version,
        policy_json={parameter_name: {"2026-01-01.2100-12-31": reused_policy.value}},
    )

    result = _copy(catalog_session, snapshot)

    assert result == LegacyPolicyPersistenceResult(
        policy_id=COPIED_POLICY_ID,
        policy_created=True,
        mapping_created=True,
    )
    [copied_policy] = recorded_writes.created_policies
    assert copied_policy.country_id == country_id
    assert copied_policy.tax_benefit_model_version_id == version.id
    assert copied_policy.policyengine_version == RUNNING_POLICYENGINE_VERSION
    [copied_value] = copied_policy.parameter_values
    assert copied_value.parameter_id == parameters[parameter_name].id
    assert copied_value.value == reused_policy.value
    assert copied_value.start_date == datetime(2026, 1, 1, tzinfo=UTC)
    assert copied_value.end_date == datetime(2100, 12, 31, tzinfo=UTC)
    assert recorded_writes.created_mappings == [
        {
            "country_id": country_id,
            "legacy_policy_id": reused_policy.legacy_policy_id,
            "source_policy_hash": snapshot.source_policy_hash,
            "policy_id": COPIED_POLICY_ID,
        }
    ]


def test_policy_with_a_country_package_the_api_does_not_run_is_copied(
    catalog_session: Session,
    recorded_writes: RecordedCopyWrites,
) -> None:
    # The copy binds content to the running catalog, as the Public API binds an
    # old policy to the running country package when it simulates one.
    _add_running_catalog(
        catalog_session, country_id="us", parameter_names=["gov.example.rate"]
    )
    snapshot = _snapshot(
        country_id="us",
        legacy_policy_id=501,
        api_version="99.0.0",
        policy_json={"gov.example.rate": {"2026": 0.2}},
    )

    result = _copy(catalog_session, snapshot)

    assert result.mapping_created is True
    assert len(recorded_writes.created_policies) == 1


def _add_earlier_copy(
    session: Session, snapshot: LegacyPolicySnapshot, *, source_policy_hash: str
) -> None:
    session.add(
        LegacyPolicyMapping(
            country_id=snapshot.country_id,
            legacy_policy_id=snapshot.legacy_policy_id,
            policy_id=EARLIER_COPY_POLICY_ID,
            source_policy_hash=source_policy_hash,
        )
    )
    session.commit()


def _reused_snapshot() -> LegacyPolicySnapshot:
    return _snapshot(
        country_id="us",
        legacy_policy_id=96567,
        api_version="1.633.2",
        policy_json={"gov.dol.minimum_wage": {"2026-01-01.2100-12-31": 9}},
    )


def test_earlier_copy_is_reused_when_the_running_catalog_is_not_published(
    catalog_session: Session,
    recorded_writes: RecordedCopyWrites,
) -> None:
    # After a PolicyEngine.py upgrade, the new release's catalog may not be
    # published yet. Writing the same v1 policy again still succeeds.
    snapshot = _reused_snapshot()
    _add_earlier_copy(
        catalog_session, snapshot, source_policy_hash=snapshot.source_policy_hash
    )

    result = _copy(catalog_session, snapshot)

    assert result == LegacyPolicyPersistenceResult(
        policy_id=EARLIER_COPY_POLICY_ID,
        policy_created=False,
        mapping_created=False,
    )
    assert recorded_writes == RecordedCopyWrites()


def test_earlier_copy_is_reused_when_the_running_catalog_lacks_its_parameter(
    catalog_session: Session,
    recorded_writes: RecordedCopyWrites,
) -> None:
    # A later release renamed or removed the parameter. The v2 copy made
    # before that keeps its own catalog version, so it is still the copy.
    _add_running_catalog(
        catalog_session, country_id="us", parameter_names=["gov.example.rate"]
    )
    snapshot = _reused_snapshot()
    _add_earlier_copy(
        catalog_session, snapshot, source_policy_hash=snapshot.source_policy_hash
    )

    result = _copy(catalog_session, snapshot)

    assert result.policy_id == EARLIER_COPY_POLICY_ID
    assert (result.policy_created, result.mapping_created) == (False, False)
    assert recorded_writes == RecordedCopyWrites()


def test_earlier_copy_with_another_source_hash_is_an_integrity_error(
    catalog_session: Session,
    recorded_writes: RecordedCopyWrites,
) -> None:
    snapshot = _reused_snapshot()
    _add_earlier_copy(
        catalog_session, snapshot, source_policy_hash="different-legacy-hash"
    )

    with pytest.raises(LegacyPolicyMappingIntegrityError, match="source hash"):
        _copy(catalog_session, snapshot)

    assert recorded_writes == RecordedCopyWrites()

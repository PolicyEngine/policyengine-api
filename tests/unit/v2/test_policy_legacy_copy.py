"""Copy committed v1 policies into v2 with the running catalog.

The catalog and mapping reads run against SQLite. The two inserts use
PostgreSQL's ON CONFLICT ON CONSTRAINT, so the tests record them instead.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from policyengine_api.data.v2.models import (
    DynamicParameter,
    LegacyPolicyMapping,
    Parameter,
    TaxBenefitModel,
    TaxBenefitModelVersion,
)
from policyengine_api.dynamic_parameters import is_dynamic_parameter
from policyengine_api.services.v2.dynamics import services as dynamic_services
from policyengine_api.services.v2.dynamics.types import (
    DynamicCreationResult,
    ResolvedDynamicCreationInput,
)
from policyengine_api.services.v2.policies import services as policy_services
from policyengine_api.services.v2.policies.types import (
    LegacyPolicyPersistenceResult,
    LegacyPolicySnapshot,
    LegacyPolicyTranslationReason,
    PolicyCreationResult,
    ResolvedPolicyCreationInput,
)
from policyengine_api.services.v2.policies.validators import (
    LegacyPolicyMappingIntegrityError,
    LegacyPolicyTranslationError,
)
from tests.fixtures.database_sessions import sqlite_v2_sessions

if TYPE_CHECKING:
    from sqlmodel import Session

RUNNING_POLICYENGINE_VERSION = "6.7.5"
COPIED_POLICY_ID = UUID("00000000-0000-0000-0000-000000000042")
EARLIER_COPY_POLICY_ID = UUID("00000000-0000-0000-0000-000000000041")
MAPPING_ID = UUID("00000000-0000-0000-0000-000000000043")
COPIED_DYNAMIC_ID = UUID("00000000-0000-0000-0000-000000000044")
US_INCOME_ELASTICITY = "gov.simulation.labor_supply_responses.elasticities.income"
UK_INCOME_ELASTICITY = "gov.simulation.labour_supply_responses.income_elasticity"
UK_OLD_INCOME_ELASTICITY = "gov.simulation.labor_supply_responses.income_elasticity"


@dataclass
class RecordedCopyWrites:
    """The policies, dynamics and mappings a copy would have inserted, in order."""

    created_policies: list[ResolvedPolicyCreationInput] = field(default_factory=list)
    created_dynamics: list[ResolvedDynamicCreationInput] = field(default_factory=list)
    created_mappings: list[dict[str, object]] = field(default_factory=list)


@pytest.fixture
def recorded_writes(monkeypatch) -> RecordedCopyWrites:
    writes = RecordedCopyWrites()

    def record_policy(_session, policy_input):
        writes.created_policies.append(policy_input)
        return PolicyCreationResult(policy_id=COPIED_POLICY_ID, created=True)

    def record_dynamic(_session, dynamic_input):
        writes.created_dynamics.append(dynamic_input)
        return DynamicCreationResult(dynamic_id=COPIED_DYNAMIC_ID, created=True)

    def record_mapping(_session, mapping):
        writes.created_mappings.append(asdict(mapping))
        return MAPPING_ID

    monkeypatch.setattr(policy_services, "create_resolved_policy", record_policy)
    monkeypatch.setattr(dynamic_services, "create_resolved_dynamic", record_dynamic)
    monkeypatch.setattr(policy_services, "create_legacy_policy_mapping", record_mapping)
    return writes


@pytest.fixture
def catalog_session():
    with sqlite_v2_sessions() as sessions, sessions(expire_on_commit=True) as session:
        yield session


def _add_running_catalog(
    session: Session, *, country_id: str, parameter_names: list[str]
) -> tuple[TaxBenefitModelVersion, dict[str, Parameter | DynamicParameter]]:
    """Store the running catalog, each parameter in its own table (C1 · 50).

    Model assumptions are ``dynamic_parameters`` rows, the rest ``parameters``
    rows, as catalog publication stores them.
    """
    model = TaxBenefitModel(name=f"policyengine-{country_id}")
    version = TaxBenefitModelVersion(
        model=model,
        version=RUNNING_POLICYENGINE_VERSION,
        current_law_id=1,
        metadata_time_periods=[2026],
    )
    parameters: dict[str, Parameter | DynamicParameter] = {
        name: (
            DynamicParameter if is_dynamic_parameter(country_id, name) else Parameter
        )(name=name, tax_benefit_model_version=version)
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
# versions older than the one API v1 ran (us 2.2.1, uk 2.130.1).
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
            "dynamic_id": None,
        }
    ]


def test_policy_with_a_country_package_the_api_does_not_run_is_copied(
    catalog_session: Session,
    recorded_writes: RecordedCopyWrites,
) -> None:
    # The copy binds content to the running catalog, as API v1 binds an
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


def _lose_mapping_race(monkeypatch, *, winning_source_hash: str) -> None:
    """Make the mapping insert find a row a concurrent copy committed first.

    The replacement returns None, as the insert does when its unique
    constraint makes it a no-op.
    """

    def insert_after_concurrent_copy(session, mapping):
        session.add(
            LegacyPolicyMapping(
                country_id=mapping.country_id,
                legacy_policy_id=mapping.legacy_policy_id,
                policy_id=EARLIER_COPY_POLICY_ID,
                source_policy_hash=winning_source_hash,
            )
        )
        session.flush()

    monkeypatch.setattr(
        policy_services, "create_legacy_policy_mapping", insert_after_concurrent_copy
    )


def test_concurrent_copy_on_another_catalog_version_is_reused(
    catalog_session: Session,
    recorded_writes: RecordedCopyWrites,
    monkeypatch,
) -> None:
    # Two first copies of the same v1 policy ran at once, for example on two
    # revisions with different PolicyEngine.py versions, so each translated
    # it to a different v2 policy. The mapping committed first is the copy.
    _add_running_catalog(
        catalog_session, country_id="us", parameter_names=["gov.dol.minimum_wage"]
    )
    snapshot = _reused_snapshot()
    _lose_mapping_race(monkeypatch, winning_source_hash=snapshot.source_policy_hash)

    result = _copy(catalog_session, snapshot)

    assert result == LegacyPolicyPersistenceResult(
        policy_id=EARLIER_COPY_POLICY_ID,
        policy_created=False,
        mapping_created=False,
    )
    assert len(recorded_writes.created_policies) == 1


def test_concurrent_copy_with_another_source_hash_is_an_integrity_error(
    catalog_session: Session,
    recorded_writes: RecordedCopyWrites,
    monkeypatch,
) -> None:
    _add_running_catalog(
        catalog_session, country_id="us", parameter_names=["gov.dol.minimum_wage"]
    )
    _lose_mapping_race(monkeypatch, winning_source_hash="different-legacy-hash")

    with pytest.raises(LegacyPolicyMappingIntegrityError, match="source hash"):
        _copy(catalog_session, _reused_snapshot())


def test_a_policy_s_model_assumptions_are_copied_into_a_dynamic(
    catalog_session: Session, recorded_writes: RecordedCopyWrites
) -> None:
    version, parameters = _add_running_catalog(
        catalog_session,
        country_id="us",
        parameter_names=["gov.dol.minimum_wage", US_INCOME_ELASTICITY],
    )
    snapshot = _snapshot(
        country_id="us",
        legacy_policy_id=501,
        api_version="1.600.0",
        policy_json={
            "gov.dol.minimum_wage": {"2026": 9},
            US_INCOME_ELASTICITY: {"2026": 0.25},
        },
    )

    result = _copy(catalog_session, snapshot)

    assert result == LegacyPolicyPersistenceResult(
        policy_id=COPIED_POLICY_ID,
        policy_created=True,
        mapping_created=True,
        dynamic_id=COPIED_DYNAMIC_ID,
        dynamic_created=True,
    )
    [copied_policy] = recorded_writes.created_policies
    assert [value.parameter_id for value in copied_policy.parameter_values] == [
        parameters["gov.dol.minimum_wage"].id
    ]
    [copied_dynamic] = recorded_writes.created_dynamics
    assert isinstance(copied_dynamic, ResolvedDynamicCreationInput)
    assert copied_dynamic.country_id == "us"
    assert copied_dynamic.tax_benefit_model_version_id == version.id
    assert [
        (value.parameter_id, value.value) for value in copied_dynamic.parameter_values
    ] == [(parameters[US_INCOME_ELASTICITY].id, 0.25)]
    assert recorded_writes.created_mappings == [
        {
            "country_id": "us",
            "legacy_policy_id": 501,
            "source_policy_hash": snapshot.source_policy_hash,
            "policy_id": COPIED_POLICY_ID,
            "dynamic_id": COPIED_DYNAMIC_ID,
        }
    ]


def test_a_uk_policy_with_only_old_spelling_assumptions_maps_to_an_empty_policy(
    catalog_session: Session, recorded_writes: RecordedCopyWrites
) -> None:
    _version, parameters = _add_running_catalog(
        catalog_session, country_id="uk", parameter_names=[UK_INCOME_ELASTICITY]
    )

    result = _copy(
        catalog_session,
        _snapshot(
            country_id="uk",
            legacy_policy_id=502,
            api_version="2.100.0",
            policy_json={UK_OLD_INCOME_ELASTICITY: {"2026": 0.3}},
        ),
    )

    assert result.dynamic_id == COPIED_DYNAMIC_ID
    [copied_policy] = recorded_writes.created_policies
    assert copied_policy.parameter_values == []
    [copied_dynamic] = recorded_writes.created_dynamics
    assert [value.parameter_id for value in copied_dynamic.parameter_values] == [
        parameters[UK_INCOME_ELASTICITY].id
    ]


def test_a_uk_policy_s_gov_dynamic_values_are_copied_into_its_dynamic(
    catalog_session: Session, recorded_writes: RecordedCopyWrites
) -> None:
    uk_tax_rate = "gov.hmrc.income_tax.rates.uk[0].rate"
    uk_obr_switch = "gov.dynamic.obr_labour_supply_assumptions"
    _version, parameters = _add_running_catalog(
        catalog_session,
        country_id="uk",
        parameter_names=[uk_tax_rate, uk_obr_switch, UK_INCOME_ELASTICITY],
    )

    result = _copy(
        catalog_session,
        _snapshot(
            country_id="uk",
            legacy_policy_id=503,
            api_version="2.174.1",
            policy_json={
                uk_tax_rate: {"2026": 0.21},
                uk_obr_switch: {"2026": False},
                UK_INCOME_ELASTICITY: {"2026": 0.1},
            },
        ),
    )

    assert result.dynamic_id == COPIED_DYNAMIC_ID
    [copied_policy] = recorded_writes.created_policies
    assert [value.parameter_id for value in copied_policy.parameter_values] == [
        parameters[uk_tax_rate].id
    ]
    [copied_dynamic] = recorded_writes.created_dynamics
    assert {
        (value.parameter_id, value.value) for value in copied_dynamic.parameter_values
    } == {
        (parameters[uk_obr_switch].id, False),
        (parameters[UK_INCOME_ELASTICITY].id, 0.1),
    }


@pytest.mark.parametrize(
    ("policy_json", "reason"),
    [
        pytest.param(
            {"gov.boe.base_rate": {"2026": 0.05}, US_INCOME_ELASTICITY: {"2026": 1}},
            LegacyPolicyTranslationReason.MISSING_PARAMETERS,
            id="assumption-missing-from-the-catalog",
        ),
        pytest.param(
            {
                UK_OLD_INCOME_ELASTICITY: {"2026": 0.3},
                UK_INCOME_ELASTICITY: {"2026": 0.4},
            },
            LegacyPolicyTranslationReason.CONFLICTING_VALUES,
            id="both-spellings-disagree",
        ),
        pytest.param(
            {UK_INCOME_ELASTICITY: {}},
            LegacyPolicyTranslationReason.EMPTY_PARAMETER_VALUES,
            id="assumption-sets-no-values",
        ),
    ],
)
def test_an_untranslatable_assumption_fails_the_copy_before_anything_is_written(
    catalog_session: Session,
    recorded_writes: RecordedCopyWrites,
    policy_json: dict[str, object],
    reason: LegacyPolicyTranslationReason,
) -> None:
    _add_running_catalog(
        catalog_session,
        country_id="uk",
        parameter_names=["gov.boe.base_rate", UK_INCOME_ELASTICITY],
    )

    with pytest.raises(LegacyPolicyTranslationError) as failure:
        _copy(
            catalog_session,
            _snapshot(
                country_id="uk",
                legacy_policy_id=503,
                api_version="2.100.0",
                policy_json=policy_json,
            ),
        )

    assert failure.value.reason == reason
    assert recorded_writes == RecordedCopyWrites()


def test_a_copy_that_loses_the_mapping_race_reports_the_mapped_dynamic(
    catalog_session: Session,
    recorded_writes: RecordedCopyWrites,
    monkeypatch,
) -> None:
    _add_running_catalog(
        catalog_session, country_id="us", parameter_names=[US_INCOME_ELASTICITY]
    )
    snapshot = _snapshot(
        country_id="us",
        legacy_policy_id=504,
        api_version="1.600.0",
        policy_json={US_INCOME_ELASTICITY: {"2026": 0.25}},
    )
    _lose_mapping_race(monkeypatch, winning_source_hash=snapshot.source_policy_hash)

    result = _copy(catalog_session, snapshot)

    # This copy created a dynamic, but the concurrent copy's mapping, made
    # before the split existed, names none; the result reports the mapping.
    assert len(recorded_writes.created_dynamics) == 1
    assert result == LegacyPolicyPersistenceResult(
        policy_id=EARLIER_COPY_POLICY_ID,
        policy_created=False,
        mapping_created=False,
        dynamic_id=None,
        dynamic_created=False,
    )


def test_a_policy_parameter_and_an_assumption_of_the_same_name_stay_apart(
    catalog_session: Session, recorded_writes: RecordedCopyWrites
) -> None:
    """The copy looks each part's names up in its own table.

    A model assumption found only among policy parameters is missing from the
    running catalog, as it would be after C1 · 50's revision moved it, and the
    copy fails before anything is written.
    """
    model = TaxBenefitModel(name="policyengine-us")
    version = TaxBenefitModelVersion(
        model=model,
        version=RUNNING_POLICYENGINE_VERSION,
        current_law_id=1,
        metadata_time_periods=[2026],
    )
    catalog_session.add_all(
        [
            version,
            Parameter(name="gov.dol.minimum_wage", tax_benefit_model_version=version),
            Parameter(name=US_INCOME_ELASTICITY, tax_benefit_model_version=version),
        ]
    )
    catalog_session.commit()
    snapshot = _snapshot(
        country_id="us",
        legacy_policy_id=502,
        api_version="1.600.0",
        policy_json={
            "gov.dol.minimum_wage": {"2026": 9},
            US_INCOME_ELASTICITY: {"2026": 0.25},
        },
    )

    with pytest.raises(LegacyPolicyTranslationError) as failure:
        _copy(catalog_session, snapshot)

    assert failure.value.reason is LegacyPolicyTranslationReason.MISSING_PARAMETERS
    assert recorded_writes == RecordedCopyWrites()

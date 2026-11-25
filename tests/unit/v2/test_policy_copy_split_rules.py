"""Splitting a stored policy copy, and merging a mapping's dynamic, without a database.

C1 · 48's command splits each stored policy that sets a model assumption into
a policy and a dynamic on the copy's own catalog version. When a legacy
mapping already names a dynamic, the split-off values join it (the user's
decision 4 of 2026-11-25).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from policyengine_api.services.v2.policy_copy_splits.transformations import (
    split_stored_policy,
)
from policyengine_api.services.v2.policy_copy_splits.types import (
    PolicyCopyRefusalReason,
)
from policyengine_api.services.v2.policy_copy_splits.validators import (
    PolicyCopySplitRefusedError,
    merge_dynamic_content,
)

from policyengine_api.data.v2.models import (
    Dynamic,
    ParameterValue,
    Policy,
    TaxBenefitModelVersion,
)
from policyengine_api.services.v2.dynamics.types import ResolvedDynamicCreationInput
from policyengine_api.services.v2.policies.transformations import (
    stored_policy_creation_input,
)
from policyengine_api.services.v2.policies.validators import (
    MAXIMUM_POLICY_PARAMETER_VALUES,
)

MODEL_ID = UUID("00000000-0000-0000-0000-00000000a001")
MODEL_VERSION_ID = UUID("00000000-0000-0000-0000-00000000a002")
OTHER_MODEL_VERSION_ID = UUID("00000000-0000-0000-0000-00000000a003")
POLICY_ID = UUID("00000000-0000-0000-0000-00000000a004")
DYNAMIC_ID = UUID("00000000-0000-0000-0000-00000000a005")
TAX_RATE_ID = UUID("00000000-0000-0000-0000-00000000b001")
OBR_SWITCH_ID = UUID("00000000-0000-0000-0000-00000000b002")
INCOME_ELASTICITY_ID = UUID("00000000-0000-0000-0000-00000000b003")
TAX_RATE = "gov.hmrc.income_tax.rates.uk[0].rate"
OBR_SWITCH = "gov.dynamic.obr_labour_supply_assumptions"
INCOME_ELASTICITY = "gov.simulation.labour_supply_responses.income_elasticity"
START_2026 = datetime(2026, 1, 1, tzinfo=UTC)
END_2026 = datetime(2026, 12, 31, tzinfo=UTC)
CATALOG_VERSION = "2.174.1"


def _model_version(model_version_id: UUID = MODEL_VERSION_ID) -> TaxBenefitModelVersion:
    return TaxBenefitModelVersion(
        id=model_version_id,
        model_id=MODEL_ID,
        version=CATALOG_VERSION,
        current_law_id=1,
        metadata_time_periods=[2026],
    )


def _stored_policy(country_id: str = "uk") -> Policy:
    return Policy(
        id=POLICY_ID,
        country_id=country_id,
        tax_benefit_model_id=MODEL_ID,
        tax_benefit_model_version_id=MODEL_VERSION_ID,
        canonicalization_version=1,
        content_hash="a" * 64,
    )


def _stored_value(
    parameter_id: UUID,
    *,
    value: object,
    start_date: datetime = START_2026,
    end_date: datetime | None = END_2026,
    dynamic_id: UUID | None = None,
) -> ParameterValue:
    """Return a stored value of the old copy, or of the dynamic `dynamic_id` names."""
    return ParameterValue(
        parameter_id=parameter_id,
        value_json=value,
        start_date=start_date,
        end_date=end_date,
        policy_id=None if dynamic_id is not None else POLICY_ID,
        dynamic_id=dynamic_id,
    )


def _stored_dynamic(model_version_id: UUID = MODEL_VERSION_ID) -> Dynamic:
    return Dynamic(
        id=DYNAMIC_ID,
        country_id="uk",
        tax_benefit_model_id=MODEL_ID,
        tax_benefit_model_version_id=model_version_id,
        canonicalization_version=1,
        content_hash="b" * 64,
    )


def _existing_dynamic(
    *values: ParameterValue, model_version_id: UUID = MODEL_VERSION_ID
) -> object:
    return stored_policy_creation_input(
        _stored_dynamic(model_version_id),
        _model_version(model_version_id),
        list(values),
    )


def _uk_split_off_dynamic(*values: ParameterValue) -> ResolvedDynamicCreationInput:
    split = split_stored_policy(
        _stored_policy(),
        _model_version(),
        [(value, OBR_SWITCH) for value in values],
    )
    assert split is not None
    return split.dynamic


def _value_triples(content: object) -> set[tuple[UUID, object, datetime | None]]:
    return {
        (value.parameter_id, value.value, value.end_date)
        for value in content.parameter_values
    }


def test_a_copy_is_split_on_its_own_catalog_version_keeping_its_values() -> None:
    split = split_stored_policy(
        _stored_policy(),
        _model_version(),
        [
            (_stored_value(TAX_RATE_ID, value=0.21), TAX_RATE),
            (_stored_value(OBR_SWITCH_ID, value=False), OBR_SWITCH),
            (
                _stored_value(INCOME_ELASTICITY_ID, value=0.1, end_date=None),
                INCOME_ELASTICITY,
            ),
        ],
    )

    assert split is not None
    for content in (split.policy, split.dynamic):
        assert content.country_id == "uk"
        assert content.tax_benefit_model_id == MODEL_ID
        assert content.tax_benefit_model_version_id == MODEL_VERSION_ID
        assert content.policyengine_version == CATALOG_VERSION
    assert _value_triples(split.policy) == {(TAX_RATE_ID, 0.21, END_2026)}
    assert isinstance(split.dynamic, ResolvedDynamicCreationInput)
    assert _value_triples(split.dynamic) == {
        (OBR_SWITCH_ID, False, END_2026),
        (INCOME_ELASTICITY_ID, 0.1, None),
    }
    assert {value.start_date for value in split.dynamic.parameter_values} == {
        START_2026
    }


def test_a_copy_holding_only_model_assumptions_splits_into_an_empty_policy() -> None:
    split = split_stored_policy(
        _stored_policy(),
        _model_version(),
        [(_stored_value(OBR_SWITCH_ID, value=False), OBR_SWITCH)],
    )

    assert split is not None
    assert split.policy.parameter_values == []
    assert _value_triples(split.dynamic) == {(OBR_SWITCH_ID, False, END_2026)}


def test_a_copy_setting_no_model_assumption_is_not_split() -> None:
    assert (
        split_stored_policy(
            _stored_policy(),
            _model_version(),
            [(_stored_value(TAX_RATE_ID, value=0.21), TAX_RATE)],
        )
        is None
    )


SPLIT_OFF_SWITCH = {(OBR_SWITCH_ID, 1, END_2026)}


@pytest.mark.parametrize(
    ("country_id", "parameter_name", "expected_dynamic_values"),
    [
        ("us", "simulation.marginal_tax_rate_delta", SPLIT_OFF_SWITCH),
        (
            "us",
            "gov.simulation.labor_supply_responses.elasticities.income",
            SPLIT_OFF_SWITCH,
        ),
        ("us", OBR_SWITCH, None),
        ("uk", OBR_SWITCH, SPLIT_OFF_SWITCH),
        ("uk", "simulation.marginal_tax_rate_delta", None),
    ],
)
def test_each_country_s_prefixes_decide_what_is_split_off(
    country_id: str,
    parameter_name: str,
    expected_dynamic_values: set[tuple[UUID, object, datetime]] | None,
) -> None:
    split = split_stored_policy(
        _stored_policy(country_id),
        _model_version(),
        [
            (_stored_value(TAX_RATE_ID, value=0.21), TAX_RATE),
            (_stored_value(OBR_SWITCH_ID, value=1), parameter_name),
        ],
    )

    if expected_dynamic_values is None:
        assert split is None
    else:
        assert split is not None
        assert _value_triples(split.dynamic) == expected_dynamic_values


def test_a_mapping_s_dynamic_and_the_split_off_values_merge_into_one() -> None:
    merged = merge_dynamic_content(
        _existing_dynamic(
            _stored_value(INCOME_ELASTICITY_ID, value=0.1, dynamic_id=DYNAMIC_ID)
        ),
        _uk_split_off_dynamic(_stored_value(OBR_SWITCH_ID, value=False)),
    )

    assert isinstance(merged, ResolvedDynamicCreationInput)
    assert merged.tax_benefit_model_version_id == MODEL_VERSION_ID
    assert merged.policyengine_version == CATALOG_VERSION
    assert _value_triples(merged) == {
        (INCOME_ELASTICITY_ID, 0.1, END_2026),
        (OBR_SWITCH_ID, False, END_2026),
    }


def test_a_value_both_dynamics_set_identically_is_kept_once() -> None:
    merged = merge_dynamic_content(
        _existing_dynamic(
            _stored_value(OBR_SWITCH_ID, value=False, dynamic_id=DYNAMIC_ID)
        ),
        _uk_split_off_dynamic(_stored_value(OBR_SWITCH_ID, value=False)),
    )

    assert _value_triples(merged) == {(OBR_SWITCH_ID, False, END_2026)}


@pytest.mark.parametrize(
    ("existing_value", "existing_end_date"),
    [
        pytest.param(True, END_2026, id="different-value"),
        # JSON true and 0 or 1 are different values, though Python compares
        # True equal to 1.
        pytest.param(0, END_2026, id="integer-for-boolean"),
        pytest.param(False, None, id="different-end-date"),
    ],
)
def test_a_value_the_two_dynamics_set_differently_refuses_the_copy(
    existing_value: object, existing_end_date: datetime | None
) -> None:
    with pytest.raises(PolicyCopySplitRefusedError) as refusal:
        merge_dynamic_content(
            _existing_dynamic(
                _stored_value(
                    OBR_SWITCH_ID,
                    value=existing_value,
                    end_date=existing_end_date,
                    dynamic_id=DYNAMIC_ID,
                )
            ),
            _uk_split_off_dynamic(_stored_value(OBR_SWITCH_ID, value=False)),
        )

    assert refusal.value.reason is PolicyCopyRefusalReason.CONFLICTING_DYNAMIC_VALUES


def test_a_mapping_s_dynamic_on_another_catalog_version_refuses_the_copy() -> None:
    with pytest.raises(PolicyCopySplitRefusedError) as refusal:
        merge_dynamic_content(
            _existing_dynamic(
                _stored_value(INCOME_ELASTICITY_ID, value=0.1, dynamic_id=DYNAMIC_ID),
                model_version_id=OTHER_MODEL_VERSION_ID,
            ),
            _uk_split_off_dynamic(_stored_value(OBR_SWITCH_ID, value=False)),
        )

    assert refusal.value.reason is PolicyCopyRefusalReason.DYNAMIC_ON_ANOTHER_CATALOG


def test_a_merged_dynamic_over_the_value_limit_refuses_the_copy() -> None:
    existing_values = [
        _stored_value(
            INCOME_ELASTICITY_ID,
            value=0.1,
            start_date=datetime(2026, 1, 1, tzinfo=UTC).replace(year=1000 + index),
            end_date=None,
            dynamic_id=DYNAMIC_ID,
        )
        for index in range(MAXIMUM_POLICY_PARAMETER_VALUES)
    ]

    with pytest.raises(PolicyCopySplitRefusedError) as refusal:
        merge_dynamic_content(
            _existing_dynamic(*existing_values),
            _uk_split_off_dynamic(_stored_value(OBR_SWITCH_ID, value=False)),
        )

    assert refusal.value.reason is PolicyCopyRefusalReason.TOO_MANY_VALUES

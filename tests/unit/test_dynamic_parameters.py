"""Which parameters a dynamic holds, and how a v1 policy's values are split."""

from typing import get_args

import pytest
from policyengine_api.dynamic_parameters import (
    DYNAMIC_PARAMETER_PREFIXES,
    ConflictingParameterSpellingsError,
    canonical_parameter_name,
    is_dynamic_parameter,
    split_legacy_policy_json,
)

from policyengine_api.supported_countries import SupportedCountryId

UK_OLD_INCOME_ELASTICITY = "gov.simulation.labor_supply_responses.income_elasticity"
UK_INCOME_ELASTICITY = "gov.simulation.labour_supply_responses.income_elasticity"
US_INCOME_ELASTICITY = "gov.simulation.labor_supply_responses.elasticities.income"


def test_every_supported_country_lists_its_prefixes() -> None:
    assert set(DYNAMIC_PARAMETER_PREFIXES) == set(get_args(SupportedCountryId))
    assert DYNAMIC_PARAMETER_PREFIXES["us"] == ("gov.simulation.", "simulation.")
    assert DYNAMIC_PARAMETER_PREFIXES["uk"] == ("gov.simulation.",)


@pytest.mark.parametrize(
    ("country_id", "parameter_name"),
    [
        ("us", US_INCOME_ELASTICITY),
        ("us", "gov.simulation.branch_to_determine_itemization"),
        ("us", "simulation.marginal_tax_rate_delta"),
        ("uk", UK_INCOME_ELASTICITY),
        ("uk", "gov.simulation.marginal_tax_rate_delta"),
    ],
)
def test_parameters_under_the_country_s_prefixes_are_dynamic(
    country_id: SupportedCountryId, parameter_name: str
) -> None:
    assert is_dynamic_parameter(country_id, parameter_name)


@pytest.mark.parametrize(
    ("country_id", "parameter_name"),
    [
        ("us", "gov.irs.credits.ctc.amount.base[0].amount"),
        # A name that only starts with the same letters is not under the prefix.
        ("us", "gov.simulations_count"),
        ("us", "simulationX.rate"),
        # The UK has no top-level simulation tree.
        ("uk", "simulation.marginal_tax_rate_delta"),
        ("uk", "gov.hmrc.income_tax.allowances.personal_allowance.amount"),
    ],
)
def test_other_parameters_are_not_dynamic(
    country_id: SupportedCountryId, parameter_name: str
) -> None:
    assert not is_dynamic_parameter(country_id, parameter_name)


def test_only_the_uk_old_labour_supply_spelling_is_rewritten() -> None:
    assert canonical_parameter_name("uk", UK_OLD_INCOME_ELASTICITY) == (
        UK_INCOME_ELASTICITY
    )
    assert canonical_parameter_name("uk", UK_INCOME_ELASTICITY) == (
        UK_INCOME_ELASTICITY
    )
    # In the US, labor_supply_responses is the parameter's own name.
    assert canonical_parameter_name("us", US_INCOME_ELASTICITY) == (
        US_INCOME_ELASTICITY
    )
    assert canonical_parameter_name("uk", "gov.hmrc.rate") == "gov.hmrc.rate"


def test_a_us_policy_is_split_into_its_policy_and_dynamic_values() -> None:
    policy_json = {
        "gov.irs.rate": {"2026-01-01.2100-12-31": 0.2},
        US_INCOME_ELASTICITY: {"2026": 0.1},
        "simulation.marginal_tax_rate_delta": {"2026": 500},
    }

    split = split_legacy_policy_json("us", policy_json)

    assert split.policy_values == {"gov.irs.rate": {"2026-01-01.2100-12-31": 0.2}}
    assert split.dynamic_values == {
        US_INCOME_ELASTICITY: {"2026": 0.1},
        "simulation.marginal_tax_rate_delta": {"2026": 500},
    }


def test_a_uk_policy_s_old_spelling_is_rewritten_into_its_dynamic() -> None:
    split = split_legacy_policy_json(
        "uk",
        {
            "gov.hmrc.rate": {"2026": 0.2},
            UK_OLD_INCOME_ELASTICITY: {"2026": 0.3},
        },
    )

    assert split.policy_values == {"gov.hmrc.rate": {"2026": 0.2}}
    assert split.dynamic_values == {UK_INCOME_ELASTICITY: {"2026": 0.3}}


def test_both_uk_spellings_of_one_parameter_merge_their_periods() -> None:
    split = split_legacy_policy_json(
        "uk",
        {
            UK_OLD_INCOME_ELASTICITY: {"2026": 0.3, "2027": 0.4},
            UK_INCOME_ELASTICITY: {"2027": 0.4, "2028": 0.5},
        },
    )

    assert split.policy_values == {}
    assert split.dynamic_values == {
        UK_INCOME_ELASTICITY: {"2026": 0.3, "2027": 0.4, "2028": 0.5}
    }


@pytest.mark.parametrize(
    ("old_spelling_values", "new_spelling_values"),
    [
        ({"2026": 0.3}, {"2026": 0.4}),
        ({"2026": 0.3}, 0.4),
        ("0.3", {"2027": 0.4}),
    ],
)
def test_both_uk_spellings_that_disagree_are_refused(
    old_spelling_values: object, new_spelling_values: object
) -> None:
    with pytest.raises(ConflictingParameterSpellingsError):
        split_legacy_policy_json(
            "uk",
            {
                UK_OLD_INCOME_ELASTICITY: old_spelling_values,
                UK_INCOME_ELASTICITY: new_spelling_values,
            },
        )


def test_a_policy_with_no_dynamic_values_is_left_whole() -> None:
    policy_json = {"gov.irs.rate": {"2026": 0.2}}

    split = split_legacy_policy_json("us", policy_json)

    assert split.policy_values == policy_json
    assert split.dynamic_values == {}
    assert split_legacy_policy_json("us", {}) == split_legacy_policy_json("uk", {})

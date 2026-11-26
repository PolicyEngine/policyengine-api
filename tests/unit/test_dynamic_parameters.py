"""Which parameters a dynamic holds, and how a v1 policy's values are split."""

from typing import get_args

import pytest

from policyengine_api.dynamic_parameters import (
    DYNAMIC_PARAMETER_PREFIXES,
    ConflictingParameterSpellingsError,
    canonical_parameter_name,
    is_dynamic_parameter,
    is_dynamic_parameter_path,
    split_legacy_policy_json,
)
from policyengine_api.supported_countries import SupportedCountryId

UK_OLD_INCOME_ELASTICITY = "gov.simulation.labor_supply_responses.income_elasticity"
UK_INCOME_ELASTICITY = "gov.simulation.labour_supply_responses.income_elasticity"
US_INCOME_ELASTICITY = "gov.simulation.labor_supply_responses.elasticities.income"
UK_OBR_LABOUR_SUPPLY_SWITCH = "gov.dynamic.obr_labour_supply_assumptions"


def test_every_supported_country_lists_its_prefixes() -> None:
    assert set(DYNAMIC_PARAMETER_PREFIXES) == set(get_args(SupportedCountryId))
    assert DYNAMIC_PARAMETER_PREFIXES["us"] == ("gov.simulation.", "simulation.")
    assert DYNAMIC_PARAMETER_PREFIXES["uk"] == ("gov.simulation.", "gov.dynamic.")


@pytest.mark.parametrize(
    ("country_id", "parameter_name"),
    [
        ("us", US_INCOME_ELASTICITY),
        ("us", "gov.simulation.branch_to_determine_itemization"),
        ("us", "simulation.marginal_tax_rate_delta"),
        ("uk", UK_INCOME_ELASTICITY),
        ("uk", "gov.simulation.marginal_tax_rate_delta"),
        ("uk", UK_OBR_LABOUR_SUPPLY_SWITCH),
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
        ("uk", "gov.dynamics_count"),
        # Only the UK keeps model assumptions under gov.dynamic.
        ("us", "gov.dynamic.obr_labour_supply_assumptions"),
    ],
)
def test_other_parameters_are_not_dynamic(
    country_id: SupportedCountryId, parameter_name: str
) -> None:
    assert not is_dynamic_parameter(country_id, parameter_name)


@pytest.mark.parametrize(
    ("country_id", "path"),
    [
        # The folders themselves, which hold only dynamic parameters.
        ("us", "gov.simulation"),
        ("us", "simulation"),
        ("uk", "gov.simulation"),
        ("uk", "gov.dynamic"),
        # Folders, brackets and parameters below them.
        ("us", "gov.simulation.labor_supply_responses"),
        ("us", "gov.simulation.labor_supply_responses.elasticities.income"),
        ("us", "simulation.marginal_tax_rate_delta"),
        ("uk", "gov.simulation.labour_supply_responses"),
        ("uk", "gov.simulation.schedule[0]"),
        ("uk", "gov.simulation.schedule[0].rate"),
        ("uk", UK_OBR_LABOUR_SUPPLY_SWITCH),
    ],
)
def test_dynamic_folders_and_everything_below_them_are_dynamic_paths(
    country_id: SupportedCountryId, path: str
) -> None:
    assert is_dynamic_parameter_path(country_id, path)


@pytest.mark.parametrize(
    ("country_id", "path"),
    [
        # "gov" holds policy parameters too.
        ("us", "gov"),
        ("uk", "gov"),
        ("us", "gov.irs"),
        ("us", "gov.simulations_count"),
        ("us", "simulationX"),
        # Each country's own folders only.
        ("us", "gov.dynamic"),
        ("uk", "simulation"),
        ("uk", "simulation.marginal_tax_rate_delta"),
        ("uk", "gov.dynamics"),
        ("us", ""),
    ],
)
def test_policy_folders_and_parameters_are_not_dynamic_paths(
    country_id: SupportedCountryId, path: str
) -> None:
    assert not is_dynamic_parameter_path(country_id, path)


def test_every_dynamic_parameter_has_a_dynamic_path() -> None:
    """A parameter is a dynamic path exactly when it is a dynamic parameter."""
    for country_id in DYNAMIC_PARAMETER_PREFIXES:
        for name in (
            US_INCOME_ELASTICITY,
            UK_INCOME_ELASTICITY,
            UK_OBR_LABOUR_SUPPLY_SWITCH,
            "simulation.marginal_tax_rate_delta",
            "gov.hmrc.rate",
            "gov.dynamics_count",
        ):
            assert is_dynamic_parameter_path(country_id, name) == (
                is_dynamic_parameter(country_id, name)
            )


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


def test_a_uk_policy_s_gov_dynamic_values_go_into_its_dynamic() -> None:
    split = split_legacy_policy_json(
        "uk",
        {
            "gov.hmrc.income_tax.rates.uk[0].rate": {"2026": 0.21},
            UK_OBR_LABOUR_SUPPLY_SWITCH: {"2026": False},
            UK_INCOME_ELASTICITY: {"2026": 0.1},
        },
    )

    assert split.policy_values == {
        "gov.hmrc.income_tax.rates.uk[0].rate": {"2026": 0.21}
    }
    assert split.dynamic_values == {
        UK_OBR_LABOUR_SUPPLY_SWITCH: {"2026": False},
        UK_INCOME_ELASTICITY: {"2026": 0.1},
    }


def test_gov_dynamic_has_one_spelling_and_is_never_rewritten() -> None:
    assert canonical_parameter_name("uk", UK_OBR_LABOUR_SUPPLY_SWITCH) == (
        UK_OBR_LABOUR_SUPPLY_SWITCH
    )


def test_publication_refuses_to_classify_an_unsupported_country() -> None:
    """A catalog country with no prefixes can't be split into the two tables."""
    from policyengine_api.data.v2.catalog.dynamic_parameter_records import (
        is_dynamic_record,
    )
    from policyengine_api.data.v2.catalog.publication_types import (
        CatalogPublicationError,
    )

    assert is_dynamic_record("uk", "gov.dynamic.obr_labour_supply_assumptions")
    with pytest.raises(CatalogPublicationError, match="'ca' is not a supported"):
        is_dynamic_record("ca", "gov.simulation.example")

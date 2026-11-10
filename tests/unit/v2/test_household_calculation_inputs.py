"""A household calculation's request fields, axis limits and pre-submission checks."""

from __future__ import annotations

from uuid import UUID

import pytest
from policyengine_api.services.v2.household_calculations.types import (
    MAXIMUM_AXIS_POINTS,
    HouseholdCalculationInput,
)
from policyengine_api.services.v2.household_calculations.validators import (
    HouseholdCalculationCountryError,
    HouseholdCalculationYearError,
    require_default_year,
    require_household_country,
)
from pydantic import ValidationError

from policyengine_api.services.v2.countries.types import CountryRead
from policyengine_api.services.v2.policies.validators import (
    PolicyParametersMissingError,
    require_policy_parameters_present,
)

HOUSEHOLD_ID = UUID("00000000-0000-4000-8000-0000000000a1")
POLICY_ID = UUID("00000000-0000-4000-8000-0000000000b1")
COUNTRIES = (
    CountryRead(id="uk", household_enabled=True, society_wide_enabled=False),
    CountryRead(id="us", household_enabled=True, society_wide_enabled=True),
)


def _axis(count: int, name: str = "employment_income") -> dict[str, object]:
    return {"name": name, "count": count, "min": 0, "max": 100_000}


def _calculation(**changes: object) -> HouseholdCalculationInput:
    fields: dict[str, object] = {"country_id": "us", "household_id": HOUSEHOLD_ID}
    fields.update(changes)
    return HouseholdCalculationInput.model_validate(fields)


def test_a_calculation_needs_only_a_country_and_a_household() -> None:
    calculation = _calculation(country_id="US")

    assert calculation.country_id == "us"
    assert calculation.policy_id is None
    assert calculation.axes is None
    assert calculation.add_missing_variables is False
    assert calculation.spm is None


def test_axis_groups_whose_grid_reaches_the_point_limit_are_accepted() -> None:
    calculation = _calculation(
        axes=[[_axis(100), _axis(100, "self_employment_income")], [_axis(100)]]
    )

    assert calculation.axes is not None
    assert [len(group) for group in calculation.axes] == [2, 1]
    assert MAXIMUM_AXIS_POINTS == 100 * 100


@pytest.mark.parametrize(
    "axes",
    [
        pytest.param([[_axis(3), _axis(4, "pension_income")]], id="uneven-group"),
        pytest.param([[_axis(101)], [_axis(100)]], id="grid-over-the-limit"),
        pytest.param([[_axis(MAXIMUM_AXIS_POINTS + 1)]], id="axis-over-the-limit"),
        pytest.param([[]], id="empty-group"),
        pytest.param([[_axis(2)]] * 9, id="too-many-groups"),
        pytest.param([[_axis(0)]], id="no-points"),
    ],
)
def test_axes_outside_the_simulation_service_limits_are_refused(axes) -> None:
    with pytest.raises(ValidationError):
        _calculation(axes=axes)


def test_an_axis_keeps_only_the_keys_its_caller_gave() -> None:
    calculation = _calculation(axes=[[_axis(5)]])

    assert calculation.axes is not None
    (group,) = calculation.axes
    (axis,) = group
    assert axis.model_dump(mode="json", exclude_unset=True) == _axis(5)


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"unknown": True}, id="unknown-field"),
        pytest.param({"spm": None}, id="explicit-null-spm"),
        pytest.param({"spm": {"geography_kind": "metro"}}, id="metro-without-id"),
        pytest.param({"add_missing_variables": "sometimes"}, id="not-a-boolean"),
        pytest.param({"country_id": "fr"}, id="unsupported-country"),
    ],
)
def test_a_malformed_calculation_is_refused(changes) -> None:
    with pytest.raises(ValidationError):
        _calculation(**changes)


def test_spm_settings_keep_only_the_fields_the_caller_chose() -> None:
    calculation = _calculation(spm={"scenario": "ce_trend"})

    assert calculation.spm is not None
    assert calculation.spm.model_dump(mode="json") == {"scenario": "ce_trend"}


def test_a_household_only_country_calculates_households() -> None:
    require_household_country(COUNTRIES, "uk")
    require_household_country(COUNTRIES, "us")

    with pytest.raises(HouseholdCalculationCountryError, match="uk"):
        require_household_country(
            (
                CountryRead(
                    id="uk", household_enabled=False, society_wide_enabled=False
                ),
            ),
            "uk",
        )


def test_a_country_without_a_countries_row_calculates_no_households() -> None:
    with pytest.raises(HouseholdCalculationCountryError, match="us"):
        require_household_country(COUNTRIES[:1], "us")


def test_a_household_without_a_default_year_is_refused() -> None:
    require_default_year(2026)

    with pytest.raises(HouseholdCalculationYearError, match="default year"):
        require_default_year(None)


def test_a_policy_with_parameters_the_running_catalog_lacks_is_refused() -> None:
    missing = ("gov.example.removed", "gov.example.renamed")

    with pytest.raises(PolicyParametersMissingError) as refused:
        require_policy_parameters_present(POLICY_ID, missing)

    assert refused.value.policy_id == POLICY_ID
    assert refused.value.missing_parameters == missing
    assert str(refused.value) == (
        f"Policy {POLICY_ID} sets parameters the running catalog version does "
        "not have: gov.example.removed, gov.example.renamed"
    )


@pytest.mark.parametrize("missing", [(), None], ids=["none-missing", "not-checked"])
def test_a_policy_with_nothing_missing_or_unchecked_is_accepted(missing) -> None:
    assert require_policy_parameters_present(POLICY_ID, missing) is None

"""The staging parity set's households calculate the same year on both sides.

API v1's ``/calculate-full`` adds missing variables for the first age period
of a person named ``you``, or else the current year; the v2 household
function adds them for the stored household's default year. A parity
household that adds missing variables must therefore name its person
``you``, or the two sides differ once the calendar year moves on.
"""

from __future__ import annotations

from datetime import date

from policyengine_api.services import household_calculation_service
from tests.fixtures.integration.live_household_calculations import YEAR
from tests.integration.test_live_v2_household_parity import parity_households


class DateIn2027(date):
    """Today is a day in 2027, a year after the households' year."""

    @classmethod
    def today(cls) -> DateIn2027:
        """Return 2027-06-01."""
        return cls(2027, 6, 1)


def test_households_that_add_variables_use_one_year_on_both_sides(
    monkeypatch,
) -> None:
    monkeypatch.setattr(household_calculation_service, "date", DateIn2027)
    adding = [
        household
        for household in parity_households(run_amount=0)
        if household.add_missing_variables
    ]

    assert adding
    for household in adding:
        v1_year = household_calculation_service.get_household_year(
            household.situation()
        )
        # The v2 side calculates the stored household's default year, YEAR.
        assert str(v1_year) == YEAR, household.name

"""Strict HTTP request models for v2 household calculations."""

from __future__ import annotations

from policyengine_api.services.v2.household_calculations.types import (
    HouseholdCalculationInput,
)


class HouseholdCalculationRequest(HouseholdCalculationInput):
    """A stored household to calculate under a stored policy, or current law.

    ``household_id`` and ``policy_id`` name records of ``country_id`` stored
    through ``/v2/households`` and ``/v2/policies``; without ``policy_id`` the
    household is calculated under current law, for the household's
    ``default_year``. Each group in ``axes`` varies its inputs together across
    ``count`` points; several groups form a grid of at most 10,000 points.
    ``add_missing_variables`` adds every variable the household lacks before
    calculating. An identical calculation that succeeded in the last 28 days
    is returned again instead of being repeated.
    """

    def to_service_input(self) -> HouseholdCalculationInput:
        """Convert the request to the calculation service's input."""
        return HouseholdCalculationInput.model_validate(
            self.model_dump(mode="python", exclude_unset=True)
        )

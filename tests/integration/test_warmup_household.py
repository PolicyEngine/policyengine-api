"""Integration guard for the startup-warmup households.

Runs the real ``policyengine_us`` simulation for each configured warmup household
to prove it is a valid situation that computes a finite result — i.e. that
``run_startup_warmup`` will actually warm the machinery rather than silently
throw and leave the service unwarmed.

Slow (~2 min: it builds the US tax-benefit system), so it is gated behind
``RUN_WARMUP_INTEGRATION=1`` and skipped in the default suite. The staging smoke
suite is the other, live guard.
"""

import importlib
import math
import os

import pytest

from policyengine_api.warmup import WARMUP_HOUSEHOLDS

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_WARMUP_INTEGRATION") != "1",
    reason="slow (builds the tax-benefit system); set RUN_WARMUP_INTEGRATION=1",
)

_COUNTRY_PACKAGES = {
    "us": "policyengine_us",
    "uk": "policyengine_uk",
    "ca": "policyengine_canada",
    "ng": "policyengine_ng",
    "il": "policyengine_il",
}


def _requested_computations(household):
    # Mirror policyengine_api.country.get_requested_computations: null leaves at
    # entity_plural/entity_id/variable/period.
    requested = []
    for entities in household.values():
        if not isinstance(entities, dict):
            continue
        for variables in entities.values():
            if not isinstance(variables, dict):
                continue
            for variable, periods in variables.items():
                if not isinstance(periods, dict):
                    continue
                for period, value in periods.items():
                    if value is None:
                        requested.append((variable, period))
    return requested


@pytest.mark.parametrize("country_id", sorted(WARMUP_HOUSEHOLDS))
def test_warmup_household_builds_and_computes_finite(country_id):
    household = WARMUP_HOUSEHOLDS[country_id]
    requested = _requested_computations(household)
    assert requested, f"{country_id} warmup household requests no computation"

    package = importlib.import_module(_COUNTRY_PACKAGES[country_id])
    system = package.CountryTaxBenefitSystem()
    simulation = package.Simulation(tax_benefit_system=system, situation=household)

    for variable, period in requested:
        result = simulation.calculate(variable, period)
        assert len(result) >= 1
        assert all(math.isfinite(float(value)) for value in result), (
            f"{country_id}: {variable}@{period} produced a non-finite value"
        )

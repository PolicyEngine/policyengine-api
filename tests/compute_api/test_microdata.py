VARIABLES_TO_TEST = [
    "household_tax",
    "household_benefits",
    "household_market_income",
    "household_net_income",
]

from policyengine_uk import Microsimulation as UKMicrosimulation
from policyengine_us import Microsimulation as USMicrosimulation
import pytest

PACKAGES_TO_TEST = []


@pytest.mark.parametrize("simulation_type", PACKAGES_TO_TEST, ids=["UK", "US"])
def test_microsimulation(simulation_type):
    simulation = simulation_type()
    for variable in VARIABLES_TO_TEST:
        simulation.calculate(variable)

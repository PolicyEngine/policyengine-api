from policyengine_core.simulations import Microsimulation

from policyengine_us import Microsimulation
from policyengine_uk import Microsimulation

def compute_cliff_impact(
    simulation: Microsimulation,
):
    cliff_gap = simulation.calculate("cliff_gap")
    is_on_cliff = simulation.calculate("is_on_cliff")
    total_cliff_gap = cliff_gap.sum()
    total_adults = simulation.calculate("is_adult").sum()
    cliff_share = is_on_cliff.sum() / total_adults
    return {
        "cliff_gap": float(total_cliff_gap),
        "cliff_share": float(cliff_share),
        "type": "cliff",
    }

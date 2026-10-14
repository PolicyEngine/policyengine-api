"""Proof fixture: a weight aggregated as a value. The rule must reject it.

``build_budgetary_impact`` holds the Simulation API line that #767 fixed. The
household frame is a MicroDataFrame weighted by ``household_weight``, so
summing ``household_weight`` through it returns the sum of squared weights.
``budgetary_impact`` makes the same mistake with a hand-built MicroSeries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from microdf import MicroSeries
from policyengine_simulation_executor.simulation_macro_output import BudgetaryImpact
from policyengine_simulation_executor.simulation_output_common import (
    _sum_output_variable,
)

if TYPE_CHECKING:
    from policyengine.core import Simulation


def build_budgetary_impact(baseline: Simulation) -> BudgetaryImpact:
    """Count households as the Simulation API did before #767."""
    return BudgetaryImpact(
        households=_sum_output_variable(
            baseline, "household_weight", entity="household"
        ),
    )


def budgetary_impact(baseline: dict) -> dict:
    """Count households by weighting the household weights by themselves."""
    households = MicroSeries(
        baseline["household_weight"], weights=baseline["household_weight"]
    )
    return {"households": households.sum()}

"""Proof fixture: entities counted with a plain sum of their weights.

The rule must accept it. ``build_budgetary_impact`` holds #767's replacement
line in the Simulation API, and ``budgetary_impact`` counts households with a
plain sum of ``household_weight``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from policyengine_simulation_executor.simulation_macro_output import BudgetaryImpact
from policyengine_simulation_executor.simulation_output_common import (
    _count_output_entities,
)

if TYPE_CHECKING:
    from policyengine.core import Simulation


def build_budgetary_impact(baseline: Simulation) -> BudgetaryImpact:
    """Count households as #767 does: a plain sum of the household weights."""
    return BudgetaryImpact(
        households=_count_output_entities(
            baseline, entity="household", weight="household_weight"
        ),
    )


def budgetary_impact(baseline: dict) -> dict:
    """Count households with a plain sum of their weights."""
    return {"households": sum(baseline["household_weight"])}

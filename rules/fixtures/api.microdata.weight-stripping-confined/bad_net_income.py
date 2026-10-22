"""Proof fixture: weights stripped before a total. The rule must reject it.

Summing the raw values of a weighted column gives an unweighted sample total,
the mirror image of #767.
"""

from __future__ import annotations

import numpy as np
from microdf import MicroSeries


def baseline_net_income(baseline: dict) -> float:
    """Total household net income over the sample's records, ignoring weights."""
    return float(np.array(baseline["household_net_income"]).sum())


def reform_net_income(reform: dict) -> float:
    """Total household net income after dropping the weights it was given."""
    income = MicroSeries(
        reform["household_net_income"], weights=reform["household_weight"]
    )
    return float(income.values.sum())

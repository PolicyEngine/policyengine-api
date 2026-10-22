"""Proof fixture: label series used only to group and filter.

The rule must accept it.
"""

from __future__ import annotations

from microdf import MicroSeries

ADULT_MIN_AGE = 18


def average_income_by_decile(baseline: dict) -> dict:
    """Average household net income in each income decile, weighted by household."""
    income = MicroSeries(
        baseline["household_net_income"], weights=baseline["household_weight"]
    )
    decile = MicroSeries(baseline["household_income_decile"])
    return income.groupby(decile).mean().to_dict()


def child_poverty_rate(baseline: dict) -> float:
    """Share of children in poverty, weighted by person."""
    in_poverty = MicroSeries(
        baseline["person_in_poverty"], weights=baseline["person_weight"]
    )
    age = MicroSeries(baseline["age"])
    return float(in_poverty[age < ADULT_MIN_AGE].mean())

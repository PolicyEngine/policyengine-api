"""Proof fixture: totals that keep their weights. The rule must accept it."""

from __future__ import annotations

from microdf import MicroSeries


def baseline_net_income(baseline: dict) -> float:
    """Total household net income, weighted by household."""
    income = MicroSeries(
        baseline["household_net_income"], weights=baseline["household_weight"]
    )
    return float(income.sum())


def reform_net_income(baseline: dict, reform: dict) -> float:
    """Total reform household net income, weighted by the baseline's households."""
    baseline_income = MicroSeries(
        baseline["household_net_income"], weights=baseline["household_weight"]
    )
    income = MicroSeries(
        reform["household_net_income"], weights=baseline_income.weights
    )
    return float(income.sum())

"""Proof fixture: unweighted label series reduced. The rule must reject it."""

from __future__ import annotations

from microdf import MicroSeries

ADULT_MIN_AGE = 18


def average_decile(baseline: dict) -> float:
    """Average the decile numbers themselves, as if they were incomes."""
    decile = MicroSeries(baseline["household_income_decile"])
    return float(decile.mean())


def children(baseline: dict) -> float:
    """Count the sample's child records, ignoring person weights."""
    age = MicroSeries(baseline["age"])
    is_child = age < ADULT_MIN_AGE
    return float(is_child.sum())

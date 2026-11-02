"""Framework-independent data exchanged by the v2 countries layers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CountryRead:
    """One served country and the calculations it supports.

    ``household_enabled`` allows household calculations and saved households;
    ``society_wide_enabled`` allows society-wide reports, and implies
    ``household_enabled``.
    """

    id: str
    household_enabled: bool
    society_wide_enabled: bool

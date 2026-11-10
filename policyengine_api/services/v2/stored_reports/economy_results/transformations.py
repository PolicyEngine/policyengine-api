"""Rebuild a report run's economy result from its result rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from policyengine_api.services.v2.stored_reports.economy_results.types import (
        EconomyResult,
        EconomyResultRows,
    )


def economy_result(rows: EconomyResultRows) -> EconomyResult:
    """Return the economy result ``rows`` hold."""
    raise NotImplementedError

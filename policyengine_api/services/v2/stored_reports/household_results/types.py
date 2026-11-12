"""The result of a household report: each simulation's calculated household.

A household report's simulations each calculate the report's stored
household under one policy. The household function stores each simulation
run's calculation in ``simulation_runs.household_result``, as the same
result document a household calculation stores in ``household_jobs.result``
(``household_calculations.types.StoredExecutionResult``). Once the report's
run has succeeded, the result is both calculations, read from those
documents.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID

    from policyengine_api.services.v2.household_calculations.types import (
        HouseholdCalculationOutput,
    )


class HouseholdResultUnreadableError(RuntimeError):
    """A succeeded household report run's calculated households cannot be read.

    A simulation run it names is missing, or holds no result document of the
    household contract's version 1 with a calculated household.
    """


@dataclass(frozen=True)
class HouseholdResultRows:
    """The result documents of a report run's simulation runs, by run ID.

    A run with no stored document maps to None; a run that does not exist is
    absent.
    """

    documents: dict[UUID, Any]


@dataclass(frozen=True)
class HouseholdReportResult:
    """A household report's result: the baseline's and the reform's calculations.

    Each is the stored household with every value the calculation filled in,
    its warnings and its SPM settings and receipt. ``reform`` is None for a
    report of the baseline alone.
    """

    baseline: HouseholdCalculationOutput
    reform: HouseholdCalculationOutput | None

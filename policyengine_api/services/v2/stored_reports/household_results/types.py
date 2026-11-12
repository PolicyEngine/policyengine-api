"""The result of a household report: each simulation's calculated household.

A household report's simulations each calculate the report's stored
household under one policy. The household function stores each simulation
run's calculation in ``simulation_runs.household_result``, as the same
result document a household calculation stores in ``household_jobs.result``
(``household_calculations.types.StoredExecutionResult``), or, for a
calculation the household function refused, its failure document
(``StoredExecutionFailure``). Once the report's run has succeeded, the result
is both calculations, read from those documents; once it has failed, each
side's failure, where its document records one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from pydantic import JsonValue

    from policyengine_api.services.v2.household_calculations.types import (
        HouseholdCalculationFailure,
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

    documents: dict[UUID, JsonValue]


@dataclass(frozen=True)
class HouseholdReportResult:
    """A household report's result: the baseline's and the reform's calculations.

    Each is the stored household with every value the calculation filled in,
    its warnings and its SPM settings and receipt. ``reform`` is None for a
    report of the baseline alone.
    """

    baseline: HouseholdCalculationOutput
    reform: HouseholdCalculationOutput | None


@dataclass(frozen=True)
class HouseholdReportFailure:
    """Why each side of a failed household report run failed, where it says.

    Each is the household function's error for that side's calculation: its
    code, message, the inputs the country model does not recognize and any
    SPM error. A side is None when it succeeded, has no failure document (a
    run failed outside its calculation, such as one Modal refused, records
    none) or has one that cannot be read; the report run's error message
    still says why it failed. ``reform`` is also None for a report of the
    baseline alone.
    """

    baseline: HouseholdCalculationFailure | None
    reform: HouseholdCalculationFailure | None

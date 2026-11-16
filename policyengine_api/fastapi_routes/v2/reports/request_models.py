"""Strict HTTP request models for v2 reports."""

from typing import Annotated

from pydantic import Field

from policyengine_api.services.v2.simulation_service.types import (
    BudgetWindowReportCreationInput,
    EconomyReportCreationInput,
    HouseholdReportCreationInput,
)


class EconomyReportCreateRequest(EconomyReportCreationInput):
    """An economy report to create; ``country_id`` must match the query's.

    Each simulation's empty object is current law. No field names a
    PolicyEngine.py version: the simulation service runs its default
    worker's.
    """


class HouseholdReportCreateRequest(HouseholdReportCreationInput):
    """A household report to create; ``country_id`` must match the query's.

    It calculates the stored household ``household_id`` in its default year
    under ``baseline`` and ``reform``; each empty object is current law, and a
    null or omitted ``reform`` makes a report of the baseline alone. No field
    names a year or a PolicyEngine.py version.
    """


class BudgetWindowReportCreateRequest(BudgetWindowReportCreationInput):
    """A budget window to create; ``country_id`` must match the query's.

    It compares ``baseline`` and ``reform`` in each of ``budget_window_size``
    years (1 to 75) from ``year``, ending in 2200 or earlier. Each
    simulation's empty object is current law, and no field names a
    PolicyEngine.py version.
    """


# A report to create: ``kind`` says which.
ReportCreateRequest = Annotated[
    EconomyReportCreateRequest
    | HouseholdReportCreateRequest
    | BudgetWindowReportCreateRequest,
    Field(discriminator="kind"),
]

"""Strict HTTP request models for v2 reports."""

from policyengine_api.services.v2.simulation_service.types import (
    EconomyReportCreationInput,
)


class ReportCreateRequest(EconomyReportCreationInput):
    """An economy report to create; ``country_id`` must match the query's.

    Each simulation's empty object is current law. No field names a
    PolicyEngine.py version: the simulation service runs its default
    worker's.
    """

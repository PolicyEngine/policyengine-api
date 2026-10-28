"""Strict HTTP request models for v2 economy reports."""

from policyengine_api.query_parameters import CountryId
from policyengine_api.services.v2.economy_reports.types import (
    EconomyReportFields,
    EconomyReportRunFields,
)


class EconomyReportCreateRequest(EconomyReportFields):
    """A new economy report; ``country_id`` must match the query's.

    ``baseline`` and ``reform`` each name a v2 policy and dynamic, and an
    empty object means current law. Options are not accepted yet.
    """

    country_id: CountryId


class EconomyReportRunRequest(EconomyReportRunFields):
    """A re-run on the current catalog version; ``{}`` reuses existing runs.

    With ``force``, both simulations are calculated again as new attempts.
    """

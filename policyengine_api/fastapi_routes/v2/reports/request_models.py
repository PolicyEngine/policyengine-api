"""Strict HTTP request models for v2 economy and household reports."""

from typing import Annotated

from pydantic import Field

from policyengine_api.query_parameters import CountryId
from policyengine_api.services.v2.economy_reports.types import (
    EconomyReportFields,
    EconomyReportRunFields,
)
from policyengine_api.services.v2.household_reports.types import (
    HouseholdReportFields,
)


class EconomyReportCreateRequest(EconomyReportFields):
    """A new economy report; ``country_id`` must match the query's.

    ``baseline`` and ``reform`` each name a v2 policy and dynamic, and an
    empty object means current law. Options are not accepted yet.
    """

    country_id: CountryId


class HouseholdReportCreateRequest(HouseholdReportFields):
    """A new household report; ``country_id`` must match the query's.

    ``baseline`` and ``reform`` each name a v2 policy of the country, and an
    empty object means current law; ``reform`` is null for a report of the
    baseline alone. It is calculated for the household's ``default_year``;
    with ``add_missing_variables``, each calculation also adds every yearly,
    monthly and eternal variable the household lacks, as ``/calculate-full``
    does. A re-run keeps the choice made when the report was created.
    """

    country_id: CountryId


ReportCreateRequest = Annotated[
    EconomyReportCreateRequest | HouseholdReportCreateRequest,
    Field(discriminator="kind"),
]


class EconomyReportRunRequest(EconomyReportRunFields):
    """A re-run of an economy or household report on the current catalog version.

    ``{}`` reuses existing runs: an economy report's simulation runs for that
    version and year, or a household report's calculations that are
    unfinished or succeeded within the last 28 days. With ``force``, each of
    the report's simulations (one for a household report of the baseline
    alone) is calculated again as a new attempt.
    """

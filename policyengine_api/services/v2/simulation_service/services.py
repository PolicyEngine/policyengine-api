"""Check simulations and reports, then ask the simulation service to create them.

Every submission to the simulation service's ``POST /simulations`` and
``POST /reports`` goes through ``SimulationSubmissionService``, so checks
that apply to both live in one place. It checks, in order, that the
country's ``countries`` row allows economy calculations (a household-only
country does not) and that each policy the submission names is stored in the
country, through the same service as ``/v2/policies``; current law names
none. Only then is the simulation service asked. The dynamics a submission
names, its region and its dataset are checked by the simulation service,
which reads them in the catalog version its default worker runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.services.v2.simulation_service.validators import (
    SubmissionStorageError,
    require_economy_country,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable
    from uuid import UUID

    from policyengine_api.services.v2.simulation_service.types import (
        CountrySource,
        EconomyReportCreationInput,
        EconomySimulationCreationInput,
        PolicySource,
        SimulationServiceClient,
        SubmittedReport,
        SubmittedSimulation,
    )


class SimulationSubmissionService:
    """Check submissions, then send them to the simulation service."""

    def __init__(
        self,
        *,
        countries: CountrySource,
        policies: PolicySource,
        client_factory: Callable[[], SimulationServiceClient],
    ) -> None:
        """Check through these sources; send through ``client_factory``'s client.

        The client is built only once a submission passes the checks, so a
        refused submission gets its own answer even when the simulation
        service is not configured.
        """
        self._countries = countries
        self._policies = policies
        self._client_factory = client_factory

    def _check(self, country_id: str, policy_ids: Iterable[UUID | None]) -> None:
        """Raise unless the country has economy calculations and stores the policies.

        Raise EconomyCalculationsUnsupportedError, then PolicyNotFoundError,
        and SubmissionStorageError when the database cannot be read.
        """
        try:
            require_economy_country(self._countries.list_countries(), country_id)
            for policy_id in dict.fromkeys(policy_ids):
                if policy_id is not None:
                    self._policies.get_policy(
                        country_id=country_id, policy_id=policy_id
                    )
        except SQLAlchemyError as error:
            msg = "V2 storage is unavailable to check the submission"
            raise SubmissionStorageError(msg) from error

    def submit_simulation(
        self, simulation: EconomySimulationCreationInput
    ) -> SubmittedSimulation:
        """Check the simulation, then have the simulation service create and start it.

        Raise the checks' errors, then the simulation service's.
        """
        self._check(simulation.country_id, (simulation.policy_id,))
        return self._client_factory().submit_simulation(simulation)

    def submit_report(self, report: EconomyReportCreationInput) -> SubmittedReport:
        """Check the report, then have the simulation service create and start it.

        Raise the checks' errors, then the simulation service's.
        """
        self._check(
            report.country_id, (report.baseline.policy_id, report.reform.policy_id)
        )
        return self._client_factory().submit_report(report)

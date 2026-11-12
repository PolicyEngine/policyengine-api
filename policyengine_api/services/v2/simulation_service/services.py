"""Check simulations and reports, then ask the simulation service to create them.

Every submission to the simulation service's ``POST /simulations`` and
``POST /reports`` (economy reports and budget windows) goes through
``SimulationSubmissionService``, so checks that apply to all of them live in
one place. It checks, in order, that the
country's ``countries`` row allows economy calculations (a household-only
country does not), that each policy the submission names is stored in the
country, through the same service as ``/v2/policies`` (current law names
none), and that none of those policies sets a parameter the running catalog
version lacks (``require_runnable_policies``, which re-runs call too).
Only then is the simulation service asked. The dynamics a submission names,
its region and its dataset are checked by the simulation service, which reads
them in the catalog version its default worker runs. Running a stored report
again (``POST /reports/{report_id}/runs``) goes through the same checks, of
the policies its simulations name.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy.exc import SQLAlchemyError

from policyengine_api.data.v2.catalog.catalog_selection_validation import (
    MetadataCatalogUnavailableError,
)
from policyengine_api.services.v2.policies.validators import (
    require_policy_parameters_present,
)
from policyengine_api.services.v2.simulation_service.validators import (
    SubmissionStorageError,
    require_economy_country,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from uuid import UUID

    from policyengine_api.services.v2.simulation_service.types import (
        BudgetWindowReportCreationInput,
        CountrySource,
        EconomyReportCreationInput,
        EconomySimulationCreationInput,
        PolicySource,
        ReportRerunInput,
        SimulationServiceClient,
        SubmittedBudgetWindow,
        SubmittedReport,
        SubmittedSimulation,
    )


@contextmanager
def _storage_failures() -> Iterator[None]:
    """Raise SubmissionStorageError for a read that failed.

    That includes the policy check's catalog query, which the policy service
    reports as MetadataCatalogUnavailableError.
    """
    try:
        yield
    except (SQLAlchemyError, MetadataCatalogUnavailableError) as error:
        msg = "V2 storage is unavailable to check the submission"
        raise SubmissionStorageError(msg) from error


def require_runnable_policies(
    policies: PolicySource, *, country_id: str, policy_ids: Iterable[UUID | None]
) -> None:
    """Raise unless each named policy is stored and its parameters all exist.

    Every policy is read before any is checked, so PolicyNotFoundError for a
    policy the country does not store comes before PolicyParametersMissingError
    for one that sets parameters the running catalog version lacks; the
    latter names the first such policy in ``policy_ids``. Current law (None)
    names no policy, and a policy the running catalog could not check passes.
    Raise SubmissionStorageError when the database or its catalog cannot be
    read. Anything else that starts a run of stored policies, such as a re-run,
    checks them here first.
    """
    with _storage_failures():
        stored_policies = [
            policies.get_policy(country_id=country_id, policy_id=policy_id)
            for policy_id in dict.fromkeys(policy_ids)
            if policy_id is not None
        ]
    for policy in stored_policies:
        require_policy_parameters_present(policy.id, policy.missing_parameters)


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
        """Raise unless the country has economy calculations and the policies can run.

        Raise EconomyCalculationsUnsupportedError, then PolicyNotFoundError,
        then PolicyParametersMissingError, and SubmissionStorageError when the
        database or its catalog cannot be read.
        """
        with _storage_failures():
            require_economy_country(self._countries.list_countries(), country_id)
        require_runnable_policies(
            self._policies, country_id=country_id, policy_ids=policy_ids
        )

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

        Both the baseline's and the reform's policies are checked, the
        baseline's first. Raise the checks' errors, then the simulation
        service's.
        """
        self._check(
            report.country_id, (report.baseline.policy_id, report.reform.policy_id)
        )
        return self._client_factory().submit_report(report)

    def submit_budget_window(
        self, report: BudgetWindowReportCreationInput
    ) -> SubmittedBudgetWindow:
        """Check the budget window, then have the simulation service create it.

        It is checked as an economy report is, then the service creates its
        runs and starts its years. Raise the checks' errors, then the
        simulation service's.
        """
        self._check(
            report.country_id, (report.baseline.policy_id, report.reform.policy_id)
        )
        return self._client_factory().submit_budget_window(report)

    def rerun_report(self, rerun: ReportRerunInput) -> None:
        """Check the stored report, then have the simulation service run it again.

        The country is checked, then the policies of the report's
        simulations, the baseline's first, as for a new report. Raise the
        checks' errors, then the simulation service's.
        """
        self._check(rerun.country_id, rerun.policy_ids)
        self._client_factory().rerun_report(rerun)

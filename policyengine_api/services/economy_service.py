"""Economic impact service backed by cached reform impacts and simulation jobs."""

import uuid

from dotenv import load_dotenv
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.constants import (
    COUNTRY_PACKAGE_VERSIONS,
    POLICYENGINE_VERSION,
    get_economy_impact_cache_version,
)
from policyengine_api.gcp_logging import logger
from policyengine_api.libs.simulation_entrypoint import (
    SimulationEntrypointClient,
    simulation_entrypoint,
)
from policyengine_api.observability import runtime as observability_runtime
from policyengine_api.observability import set_runtime_context
from policyengine_api.observability.stages import ECONOMY_ANNUAL_STAGES, Stage
from policyengine_api.request_context import (
    incoming_observability_id,
    resolve_observability_id,
    restore_observability_id,
    start_observability_id,
)
from policyengine_api.runtime_cache.core import CacheCoordinationError
from policyengine_api.runtime_cache.reform_impacts import (
    CachedReformImpact,
    ReformImpactStartClaim,
)
from policyengine_api.services.budget_window_cache import BudgetWindowCache
from policyengine_api.services.economic_impact_request import EconomicImpactRequest
from policyengine_api.services.economy_budget_window_results import (
    BudgetWindowResultsMixin,
)
from policyengine_api.services.economy_budget_window_submission import (
    BudgetWindowSubmissionMixin,
)
from policyengine_api.services.economy_impact_execution import (
    ImpactExecutionMixin,
)
from policyengine_api.services.economy_impact_types import (
    BUDGET_WINDOW_CLAIM_ATTEMPTS,
    BUDGET_WINDOW_LISTED_COMPUTING_YEARS,
    BUDGET_WINDOW_MAX_ACTIVE_YEARS,
    BUDGET_WINDOW_MAX_END_YEAR,
    BUDGET_WINDOW_MAX_YEARS,
    BUDGET_WINDOW_SUBMISSION_VALIDATION_ERROR_STATUS_CODES,
    COMPLETE_STATUSES,
    COMPUTING_STATUS,
    LOCAL_AREA_BREAKDOWN_FAILURE_SECONDS,
    LOCAL_AREA_BREAKDOWN_REFUSAL_STATUS_CODES,
    LOCAL_AREA_BREAKDOWN_RETRY_NOTE,
    LOCAL_AREA_BREAKDOWN_SIMULATION_KIND,
    REFORM_IMPACT_START_CLAIM_ATTEMPTS,
    BudgetWindowEconomicImpactResult,
    BudgetWindowYearProgress,
    EconomicImpactResult,
    EconomicImpactSetupOptions,
    ImpactAction,
    ImpactStatus,
    RuntimeBundleIdentity,
    SimulationOptions,
)
from policyengine_api.services.economy_simulation_requests import (
    SimulationRequestMixin,
)
from policyengine_api.services.economy_stored_impacts import (
    StoredImpactMixin,
)
from policyengine_api.services.policy_service import PolicyService
from policyengine_api.services.reform_impacts_service import (
    ReformImpactHandoffError,
    ReformImpactsService,
)
from policyengine_api.worker_spm import validate_worker_spm

__all__ = [
    "BUDGET_WINDOW_CLAIM_ATTEMPTS",
    "BUDGET_WINDOW_LISTED_COMPUTING_YEARS",
    "BUDGET_WINDOW_MAX_ACTIVE_YEARS",
    "BUDGET_WINDOW_MAX_END_YEAR",
    "BUDGET_WINDOW_MAX_YEARS",
    "BUDGET_WINDOW_SUBMISSION_VALIDATION_ERROR_STATUS_CODES",
    "COMPLETE_STATUSES",
    "COMPUTING_STATUS",
    "LOCAL_AREA_BREAKDOWN_FAILURE_SECONDS",
    "LOCAL_AREA_BREAKDOWN_REFUSAL_STATUS_CODES",
    "LOCAL_AREA_BREAKDOWN_RETRY_NOTE",
    "LOCAL_AREA_BREAKDOWN_SIMULATION_KIND",
    "REFORM_IMPACT_START_CLAIM_ATTEMPTS",
    "BudgetWindowEconomicImpactResult",
    "BudgetWindowYearProgress",
    "EconomicImpactResult",
    "EconomicImpactSetupOptions",
    "EconomyService",
    "ImpactAction",
    "ImpactStatus",
    "RuntimeBundleIdentity",
    "SimulationOptions",
    "budget_window_cache",
]

load_dotenv()

budget_window_cache = BudgetWindowCache()


class EconomyService(
    BudgetWindowSubmissionMixin,
    BudgetWindowResultsMixin,
    ImpactExecutionMixin,
    StoredImpactMixin,
    SimulationRequestMixin,
):
    """Service that calculates the economic impact of policy reforms.

    It backs the /economy routes, which have no table of their own, so it reads
    policies and cached reform impacts through the other services.
    """

    def __init__(
        self,
        *,
        primary_session_factory: sessionmaker[Session] | None = None,
        policy_service_: PolicyService | None = None,
        reform_impacts_service_: ReformImpactsService | None = None,
        budget_window_cache_: BudgetWindowCache | None = None,
        simulation_entrypoint_: SimulationEntrypointClient | None = None,
    ) -> None:
        """Inject collaborators; omitted ones are built lazily or use the defaults."""
        self._primary_session_factory = primary_session_factory
        self._injected_policy_service = policy_service_
        self._injected_reform_impacts_service = reform_impacts_service_
        self._injected_budget_window_cache = budget_window_cache_
        self._injected_simulation_entrypoint = simulation_entrypoint_

    @property
    def _policies(self) -> PolicyService:
        if self._injected_policy_service is None:
            self._injected_policy_service = PolicyService(self._primary_session_factory)
        return self._injected_policy_service

    @property
    def _reform_impacts(self) -> ReformImpactsService:
        if self._injected_reform_impacts_service is None:
            self._injected_reform_impacts_service = ReformImpactsService()
        return self._injected_reform_impacts_service

    @property
    def _budget_window_cache(self) -> BudgetWindowCache:
        return self._injected_budget_window_cache or budget_window_cache

    @property
    def _simulation_gateway(self) -> SimulationEntrypointClient:
        return self._injected_simulation_entrypoint or simulation_entrypoint

    @observability_runtime.span(ECONOMY_ANNUAL_STAGES.name(Stage.ECONOMY_REQUEST))
    def get_economic_impact(
        self,
        impact_request: EconomicImpactRequest,
        time_period: str,
    ) -> EconomicImpactResult:
        """Calculate the society-wide economic impact of a policy reform.

        Return a result whose status is "ok" with the impact JSON in ``data``,
        "computing" while the calculation runs, or "error" with a ``message``.
        Unexpected failures are logged and re-raised.
        """
        set_runtime_context(
            country_id=impact_request.country_id,
            policy_id=impact_request.policy_id,
            baseline_policy_id=impact_request.baseline_policy_id,
            simulation_year=time_period,
        )
        economic_impact_setup_options: EconomicImpactSetupOptions | None = None
        try:
            # Normalize region early for US; this allows us to accommodate legacy
            # regions that don't contain a region prefix.
            impact_request = self._with_normalized_region(impact_request)

            economic_impact_setup_options = self._build_economic_impact_setup_options(
                impact_request,
                time_period=time_period,
            )

            return self._get_or_create_economic_impact(
                setup_options=economic_impact_setup_options,
            )

        except Exception as e:
            logger.log_struct(
                {
                    "message": "Error getting economic impact",
                    "error_type": type(e).__name__,
                },
                severity="ERROR",
            )
            raise
        finally:
            if (
                economic_impact_setup_options is not None
                and economic_impact_setup_options.observability_id is not None
            ):
                # The report identifier is selected inside a nested stage span.
                # Reapply it here while the outer economy-request span is current
                # so an identifier query returns that complete request duration.
                set_runtime_context(
                    observability_id=(economic_impact_setup_options.observability_id)
                )

    def _build_economic_impact_setup_options(
        self,
        impact_request: EconomicImpactRequest,
        *,
        time_period: str,
    ) -> EconomicImpactSetupOptions:
        country_id = impact_request.country_id
        options = impact_request.options
        if impact_request.dataset != "default":
            msg = "Custom datasets are not supported for economy calculations"
            raise ValueError(msg)
        self._validate_breakdown(impact_request)
        resolved_spm = validate_worker_spm(
            country_id,
            options.get("spm"),
            gateway=self._simulation_gateway,
            policyengine_version=POLICYENGINE_VERSION,
            model_version=COUNTRY_PACKAGE_VERSIONS.get(country_id),
        )
        if resolved_spm is not None:
            options = {**options, "spm": resolved_spm}
        submission_claim_id = self._create_submission_claim_id()
        cache_version = get_economy_impact_cache_version(
            country_id, impact_request.api_version
        )
        country_package_version = COUNTRY_PACKAGE_VERSIONS.get(country_id)
        resolved_dataset = "default"
        resolved_data_version = None
        policyengine_version = (
            POLICYENGINE_VERSION if country_id in {"us", "uk"} else None
        )
        options_hash = self._build_options_hash(
            options=options,
            bundle=RuntimeBundleIdentity(
                dataset=resolved_dataset,
                model_version=country_package_version,
                policyengine_version=policyengine_version,
                data_version=resolved_data_version,
            ),
        )

        return EconomicImpactSetupOptions.model_validate(
            {
                "submission_claim_id": submission_claim_id,
                "observability_id": None,
                "country_id": country_id,
                "reform_policy_id": impact_request.policy_id,
                "baseline_policy_id": impact_request.baseline_policy_id,
                "region": impact_request.region,
                "dataset": resolved_dataset,
                "time_period": time_period,
                "options": options,
                "api_version": cache_version,
                "target": impact_request.target,
                "model_version": country_package_version,
                "policyengine_version": policyengine_version,
                "data_version": resolved_data_version,
                "runtime_app_name": None,
                "options_hash": options_hash,
            }
        )

    @observability_runtime.span(
        ECONOMY_ANNUAL_STAGES.name(Stage.ECONOMY_RESOLVE_CACHED_OR_NEW)
    )
    def _get_or_create_economic_impact(
        self, setup_options: EconomicImpactSetupOptions
    ) -> EconomicImpactResult:
        logger.log_struct(
            {
                "message": (
                    "Received request for economic impact; checking if already in "
                    "reform_impacts table"
                ),
                **setup_options.model_dump(),
            },
            severity="INFO",
        )

        most_recent_impact = self._get_reusable_impact(setup_options)
        impact_action: ImpactAction = self._determine_impact_action(
            most_recent_impact=most_recent_impact
        )
        if most_recent_impact is not None:
            setup_options.observability_id = restore_observability_id(
                getattr(most_recent_impact, "observability_id", None)
            )
        if impact_action == ImpactAction.CREATE:
            return self._create_economic_impact(setup_options, impact_action)

        observability_runtime.event(
            "economy.cache_decision",
            attributes={"cache_event": impact_action.value},
        )
        return self._answer_from_stored_impact(
            setup_options, impact_action, most_recent_impact
        )

    def _answer_from_stored_impact(
        self,
        setup_options: EconomicImpactSetupOptions,
        impact_action: ImpactAction,
        most_recent_impact: CachedReformImpact | None,
    ) -> EconomicImpactResult:
        """Return a stored impact's result, its failure, or its execution's progress."""
        if impact_action == ImpactAction.COMPLETED:
            logger.log_struct(
                {
                    "message": (
                        "Found completed economic impact in db; returning result"
                    ),
                    **setup_options.model_dump(),
                },
                severity="INFO",
            )
            return self._handle_completed_impact(
                setup_options=setup_options,
                most_recent_impact=most_recent_impact,
            )

        if impact_action == ImpactAction.FAILED:
            return self._handle_failed_impact(most_recent_impact=most_recent_impact)

        if impact_action == ImpactAction.COMPUTING:
            logger.log_struct(
                {
                    "message": (
                        "Found computing economic impact record in db; confirming this "
                        "is still computing"
                    ),
                    **setup_options.model_dump(),
                },
                severity="INFO",
            )
            return self._handle_computing_impact(
                setup_options=setup_options,
                most_recent_impact=most_recent_impact,
            )

        msg = f"Unexpected impact action: {impact_action}"
        raise ValueError(msg)

    def _create_economic_impact(
        self,
        setup_options: EconomicImpactSetupOptions,
        impact_action: ImpactAction,
    ) -> EconomicImpactResult:
        """Submit a new simulation unless another request already owns submitting it."""
        existing_claim = self._claim_reform_impact_submission(setup_options)

        # The identifier above was selected while the runtime-resolution
        # stage was current. Reapply it now so the containing cache-decision
        # span carries the same report identifier.
        if setup_options.observability_id is not None:
            set_runtime_context(observability_id=setup_options.observability_id)
        observability_runtime.event(
            "economy.cache_decision",
            attributes={"cache_event": impact_action.value},
        )
        if existing_claim is not None:
            logger.log_struct(
                {
                    "message": "Another request owns this reform-impact submission",
                    **setup_options.model_dump(),
                },
                severity="INFO",
            )
            return EconomicImpactResult.computing()
        logger.log_struct(
            {
                "message": (
                    "No previous economic impact record found in db; creating new "
                    "simulation run"
                ),
                **setup_options.model_dump(),
            },
            severity="INFO",
        )
        try:
            result = self._handle_create_impact(
                setup_options=setup_options,
            )
        except ReformImpactHandoffError:
            # The upstream job exists, but its polling pointer was not
            # durably handed off. Retain the claim until expiry so another
            # request cannot immediately submit a duplicate job.
            raise
        except Exception:
            self._release_reform_impact_start(setup_options)
            raise
        self._release_reform_impact_start(setup_options)
        return result

    def _claim_reform_impact_submission(
        self, setup_options: EconomicImpactSetupOptions
    ) -> ReformImpactStartClaim | None:
        """Resolve the runtime bundle, then claim the right to submit the simulation.

        Return None when this request now owns the submission, or the claim of the
        request that does. Raise CacheCoordinationError if ownership keeps changing.
        """
        existing_claim = None
        with observability_runtime.span(
            ECONOMY_ANNUAL_STAGES.name(Stage.ECONOMY_RESOLVE_RUNTIME_BUNDLE)
        ):
            self._resolve_runtime_bundle_for_setup_options(setup_options)
            observability_id_candidate = resolve_observability_id(
                incoming_observability_id()
            )
            for _attempt in range(REFORM_IMPACT_START_CLAIM_ATTEMPTS):
                if self._claim_reform_impact_start(
                    setup_options,
                    observability_id_candidate,
                ):
                    setup_options.observability_id = start_observability_id(
                        observability_id_candidate
                    )
                    break
                existing_claim = self._get_reform_impact_start_claim(setup_options)
                if existing_claim is None:
                    continue
                setup_options.observability_id = restore_observability_id(
                    existing_claim.observability_id
                )
                break
            else:
                msg = "reform-impact submission ownership changed repeatedly"
                raise CacheCoordinationError(msg)
        return existing_claim

    def _create_submission_claim_id(self) -> str:
        """Create an opaque token for one submission ownership claim."""
        return str(uuid.uuid4())

"""Stored reform impacts: cache identity, lookup, start claims and status records."""

import datetime
from typing import Any

from policyengine_api.gcp_logging import logger
from policyengine_api.observability import runtime as observability_runtime
from policyengine_api.observability.stages import ECONOMY_ANNUAL_STAGES, Stage
from policyengine_api.runtime_cache.reform_impacts import (
    CachedReformImpact,
    ReformImpactIdentity,
    ReformImpactScope,
    ReformImpactStartClaim,
)
from policyengine_api.services.economy_impact_types import (
    EconomicImpactSetupOptions,
    ImpactAction,
    ImpactStatus,
    RuntimeBundleIdentity,
)
from policyengine_api.services.reform_impacts_service import ReformImpactExecution


class StoredImpactMixin:
    """Read, claim and record the stored reform impacts of a request."""

    def _resolve_runtime_bundle_for_setup_options(
        self,
        setup_options: EconomicImpactSetupOptions,
    ) -> None:
        if setup_options.runtime_app_name is None:
            (
                setup_options.runtime_app_name,
                setup_options.model_version,
            ) = self._simulation_gateway.resolve_app_name(
                setup_options.country_id,
                setup_options.model_version,
                policyengine_version=setup_options.policyengine_version,
            )

        setup_options.options_hash = self._build_options_hash(
            options=setup_options.options,
            bundle=self._runtime_bundle(setup_options),
        )

    @staticmethod
    def _runtime_bundle(
        setup_options: EconomicImpactSetupOptions,
    ) -> RuntimeBundleIdentity:
        """Return the dataset and package versions these setup options resolved."""
        return RuntimeBundleIdentity(
            dataset=setup_options.dataset,
            model_version=setup_options.model_version,
            policyengine_version=setup_options.policyengine_version,
            data_version=setup_options.data_version,
            runtime_app_name=setup_options.runtime_app_name,
        )

    @staticmethod
    def _reform_impact_scope(
        setup_options: EconomicImpactSetupOptions,
    ) -> ReformImpactScope:
        """Return the policy pair, region, dataset and period of these options."""
        return ReformImpactScope(
            country_id=setup_options.country_id,
            reform_policy_id=setup_options.reform_policy_id,
            baseline_policy_id=setup_options.baseline_policy_id,
            region=setup_options.region,
            dataset=setup_options.dataset,
            time_period=setup_options.time_period,
        )

    def _reform_impact_identity(
        self,
        setup_options: EconomicImpactSetupOptions,
    ) -> ReformImpactIdentity:
        """Return the cache identity of the impact these setup options describe."""
        return ReformImpactIdentity(
            scope=self._reform_impact_scope(setup_options),
            api_version=setup_options.api_version,
            options_hash=setup_options.options_hash,
        )

    def _reform_impact_start_claim_scope_arguments(
        self,
        setup_options: EconomicImpactSetupOptions,
    ) -> dict[str, Any]:
        if not setup_options.options_hash:
            msg = "resolved reform-impact options hash is required"
            raise ValueError(msg)
        return {
            "identity": self._reform_impact_identity(setup_options),
            "target": setup_options.target,
        }

    def _reform_impact_start_claim_arguments(
        self,
        setup_options: EconomicImpactSetupOptions,
        observability_id: str | None = None,
    ) -> dict[str, Any]:
        resolved_observability_id = observability_id or setup_options.observability_id
        if resolved_observability_id is None:
            msg = "reform-impact observability identifier is required"
            raise ValueError(msg)
        return {
            **self._reform_impact_start_claim_scope_arguments(setup_options),
            "claim_token": setup_options.submission_claim_id,
            "observability_id": resolved_observability_id,
        }

    def _claim_reform_impact_start(
        self,
        setup_options: EconomicImpactSetupOptions,
        observability_id: str,
    ) -> bool:
        return self._reform_impacts.claim_reform_impact_start(
            **self._reform_impact_start_claim_arguments(
                setup_options,
                observability_id,
            )
        )

    def _get_reform_impact_start_claim(
        self,
        setup_options: EconomicImpactSetupOptions,
    ) -> ReformImpactStartClaim | None:
        return self._reform_impacts.get_reform_impact_start_claim(
            **self._reform_impact_start_claim_scope_arguments(setup_options)
        )

    def _release_reform_impact_start(
        self,
        setup_options: EconomicImpactSetupOptions,
    ) -> None:
        self._reform_impacts.release_reform_impact_start(
            **self._reform_impact_start_claim_arguments(setup_options)
        )

    def _get_reusable_impact(
        self, setup_options: EconomicImpactSetupOptions
    ) -> CachedReformImpact | None:
        """Return the newest stored impact these options can reuse, if there is one.

        A finished impact computed by a different worker application than this
        request now resolves to is refetched under the refreshed options hash, and
        dropped unless one matches it exactly.
        """
        most_recent_impact: CachedReformImpact | None = self._get_most_recent_impact(
            setup_options=setup_options
        )
        if most_recent_impact and self._should_refresh_cached_impact(
            setup_options=setup_options,
            most_recent_impact=most_recent_impact,
        ):
            most_recent_impact = self._get_most_recent_impact(setup_options)
            if (
                not most_recent_impact
                or most_recent_impact.options_hash != setup_options.options_hash
            ):
                most_recent_impact = None
        return most_recent_impact

    def _get_previous_impacts(
        self,
        scope: ReformImpactScope,
        *,
        options_hash: str,
        api_version: str,
    ) -> list[CachedReformImpact]:
        """Fetch any previous simulation runs for the given policy reform."""
        return self._reform_impacts.get_all_reform_impacts_by_options_hash_prefix(
            ReformImpactIdentity(
                scope=scope,
                api_version=api_version,
                options_hash=options_hash,
            ),
            self._build_options_hash_lookup_pattern(options_hash),
        )

    def _get_most_recent_impact(
        self,
        setup_options: EconomicImpactSetupOptions,
    ) -> CachedReformImpact | None:
        """Return the newest cached impact for these options, or None if there is none.

        An impact with exactly this options hash wins; otherwise the newest impact
        whose hash extends this one (with extra bundle fields) is used.
        """
        previous_impacts = self._get_previous_impacts(
            self._reform_impact_scope(setup_options),
            options_hash=setup_options.options_hash,
            api_version=setup_options.api_version,
        )

        if not previous_impacts:
            return None

        for impact in previous_impacts:
            if impact.options_hash == setup_options.options_hash:
                return impact

        return previous_impacts[0]

    def _determine_impact_action(
        self,
        most_recent_impact: CachedReformImpact | None,
    ) -> ImpactAction:
        if not most_recent_impact:
            return ImpactAction.CREATE

        status = most_recent_impact.status
        if status == ImpactStatus.OK.value:
            return ImpactAction.COMPLETED
        if status == ImpactStatus.ERROR.value:
            return ImpactAction.FAILED
        if status == ImpactStatus.COMPUTING.value:
            return ImpactAction.COMPUTING
        msg = f"Unknown impact status: {status}"
        raise ValueError(msg)

    def _build_options_hash(
        self,
        options: dict,
        bundle: RuntimeBundleIdentity,
    ) -> str:
        option_pairs = "&".join(f"{key}={options[key]}" for key in sorted(options))
        bundle_parts = [
            f"dataset={bundle.dataset}",
            f"model_version={bundle.model_version}",
        ]
        if bundle.data_version:
            bundle_parts.append(f"data_version={bundle.data_version}")
        if bundle.policyengine_version:
            bundle_parts.append(f"policyengine_version={bundle.policyengine_version}")
        if options.get("spm") is not None:
            bundle_parts.append("spm_provenance_schema=canonical-spm-comparison-v2")
        if bundle.runtime_app_name:
            bundle_parts.append(f"runtime_app_name={bundle.runtime_app_name}")
        return "[" + "&".join([option_pairs, *bundle_parts]).strip("&") + "]"

    def _build_options_hash_lookup_pattern(self, options_hash: str) -> str:
        escaped_options_hash = (
            options_hash.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        if options_hash.endswith("]"):
            return f"{escaped_options_hash[:-1]}&%"
        return f"{escaped_options_hash}%"

    def _extract_cached_result(self, most_recent_impact: CachedReformImpact) -> dict:
        try:
            return self._parse_json_object(most_recent_impact.reform_impact_json)
        except (TypeError, ValueError):
            return {}

    def _should_refresh_cached_impact(
        self,
        setup_options: EconomicImpactSetupOptions,
        most_recent_impact: CachedReformImpact,
    ) -> bool:
        if most_recent_impact.status == ImpactStatus.COMPUTING.value:
            return False

        cached_result = self._extract_cached_result(most_recent_impact)
        cached_resolved_app_name = cached_result.get("resolved_app_name")
        try:
            runtime_app_name, resolved_model_version = (
                self._simulation_gateway.resolve_app_name(
                    setup_options.country_id,
                    setup_options.model_version,
                    policyengine_version=setup_options.policyengine_version,
                )
            )
        except Exception:  # noqa: BLE001  # an unresolvable worker app keeps the cached impact
            return False

        setup_options.runtime_app_name = runtime_app_name
        setup_options.model_version = resolved_model_version
        setup_options.options_hash = self._build_options_hash(
            options=setup_options.options,
            bundle=self._runtime_bundle(setup_options),
        )
        if (
            not isinstance(cached_resolved_app_name, str)
            or not cached_resolved_app_name
        ):
            return True

        return runtime_app_name != cached_resolved_app_name

    # Note: The following methods that interface with the ReformImpactsService
    # are written separately because the service relies upon mutating an original
    # 'computing' record to 'ok' or 'error' status, rather than creating a new record.
    # This should be addressed in the future.
    @observability_runtime.span(
        ECONOMY_ANNUAL_STAGES.name(Stage.ECONOMY_PERSIST_COMPUTING)
    )
    def _set_reform_impact_computing(
        self,
        setup_options: EconomicImpactSetupOptions,
        execution_id: str,
    ) -> None:
        """Record the impact as "computing" for this run; log and re-raise errors."""
        try:
            self._reform_impacts.set_reform_impact(
                identity=self._reform_impact_identity(setup_options),
                execution=ReformImpactExecution(
                    execution_id=execution_id,
                    start_time=datetime.datetime.now(),  # noqa: DTZ005  # start_time is a naive column that has always held local time
                    observability_id=setup_options.observability_id,
                ),
                options=setup_options.options,
                status=ImpactStatus.COMPUTING.value,
                reform_impact_json={},
            )
        except Exception as e:
            logger.log_struct(
                {
                    "message": f"Error inserting computing record: {e!s}",
                    **setup_options.model_dump(),
                }
            )
            raise

    @observability_runtime.span(
        ECONOMY_ANNUAL_STAGES.name(Stage.ECONOMY_PERSIST_COMPLETED)
    )
    def _set_reform_impact_complete(
        self,
        setup_options: EconomicImpactSetupOptions,
        reform_impact_json: dict[str, Any],
        execution_id: str,
    ) -> None:
        """Record the impact as "ok" with its result JSON; log and re-raise errors."""
        try:
            self._reform_impacts.set_complete_reform_impact(
                execution_id=execution_id,
                reform_impact_json=reform_impact_json,
            )
        except Exception as e:
            logger.log_struct(
                {
                    "message": (f"Error setting completed reform impact record: {e!s}"),
                    **setup_options.model_dump(),
                }
            )
            raise

    @observability_runtime.span(
        ECONOMY_ANNUAL_STAGES.name(Stage.ECONOMY_PERSIST_FAILED)
    )
    def _set_reform_impact_error(
        self,
        setup_options: EconomicImpactSetupOptions,
        message: str,
        execution_id: str,
        error_code: str | None = None,
        keep_seconds: int | None = None,
    ) -> None:
        """Record the impact as "error" with its message; log and re-raise errors.

        ``keep_seconds`` keeps the error for that long instead of the usual
        30 days.
        """
        # Optional fields are passed only when set, as before keep_seconds existed.
        optional_fields: dict[str, Any] = {}
        if error_code is not None:
            optional_fields["error_code"] = error_code
        if keep_seconds is not None:
            optional_fields["keep_seconds"] = keep_seconds
        try:
            self._reform_impacts.set_error_reform_impact(
                execution_id=execution_id,
                message=message,
                **optional_fields,
            )
        except Exception as e:
            logger.log_struct(
                {
                    "message": f"Error setting error reform impact record: {e!s}",
                    **setup_options.model_dump(),
                }
            )
            raise

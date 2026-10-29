"""Simulation API requests: check the region and breakdown, build the payload."""

import datetime
import hashlib
import json
from dataclasses import replace
from typing import Any

import httpx

from policyengine_api.constants import LOCAL_AREA_BREAKDOWN_REGIONS
from policyengine_api.data.congressional_districts import (
    get_valid_congressional_districts,
    get_valid_state_codes,
    normalize_us_region,
)
from policyengine_api.data.places import validate_place_code
from policyengine_api.data.uk_regions import (
    describe_accepted_uk_regions,
    resolve_uk_region,
)
from policyengine_api.json_types import JSONValue
from policyengine_api.observability import runtime as observability_runtime
from policyengine_api.observability.stages import ECONOMY_ANNUAL_STAGES, Stage
from policyengine_api.services.economic_impact_request import (
    LOCAL_AREA_BREAKDOWN,
    EconomicImpactRequest,
    LocalAreaBreakdown,
)
from policyengine_api.services.economy_impact_types import (
    LOCAL_AREA_BREAKDOWN_REFUSAL_STATUS_CODES,
    LOCAL_AREA_BREAKDOWN_SIMULATION_KIND,
    EconomicImpactResult,
    EconomicImpactSetupOptions,
    ImpactPolicies,
    SimulationOptions,
)
from policyengine_api.services.policy_service import PolicyNotFoundError


class SimulationRequestMixin:
    """Build the simulation API request for an impact, and read its refusals."""

    @observability_runtime.span(ECONOMY_ANNUAL_STAGES.name(Stage.ECONOMY_LOAD_POLICIES))
    def _get_policy_jsons(
        self,
        country_id: str,
        baseline_policy_id: int,
        reform_policy_id: int,
    ) -> ImpactPolicies:
        """Return the baseline and reform policies' JSON objects.

        A policy ID belongs to one country. Raise PolicyNotFoundError with the
        reform policy's ID, then the baseline policy's, for each one this
        country does not have, so callers can check before they claim or
        submit any work.
        """
        baseline = self._policies.get_policy_json(
            country_id,
            baseline_policy_id,
        )
        reform = self._policies.get_policy_json(
            country_id,
            reform_policy_id,
        )
        missing_policy_ids = [
            policy_id
            for policy_id, policy_json in (
                (reform_policy_id, reform),
                (baseline_policy_id, baseline),
            )
            if policy_json is None
        ]
        if missing_policy_ids:
            # dict.fromkeys drops a repeated ID and keeps the order.
            raise PolicyNotFoundError(*dict.fromkeys(missing_policy_ids))
        return ImpactPolicies(
            baseline=self._parse_json_object(baseline),
            reform=self._parse_json_object(reform),
        )

    @staticmethod
    def _parse_json_object(value: JSONValue) -> dict[str, Any]:
        """Accept ORM-decoded objects and legacy JSON text at a read boundary."""
        parsed = json.loads(value) if isinstance(value, str) else value
        if not isinstance(parsed, dict):
            msg = "Expected a JSON object"
            raise TypeError(msg)
        return parsed

    @staticmethod
    def _with_normalized_region(
        impact_request: EconomicImpactRequest,
    ) -> EconomicImpactRequest:
        """Give a US request its prefixed region, so legacy bare regions still work."""
        if impact_request.country_id != "us":
            return impact_request
        return replace(
            impact_request, region=normalize_us_region(impact_request.region)
        )

    @staticmethod
    def _validate_breakdown(impact_request: EconomicImpactRequest) -> None:
        """Reject a local-area breakdown the simulation API has no run for.

        The breakdown covers the whole UK or one UK country, so the region must
        be exactly one of ``LOCAL_AREA_BREAKDOWN_REGIONS``: a constituency or
        local authority is already a single area, and any other spelling would
        fail in the simulation API instead. It computes no cliff impacts, so
        ``target=cliff`` is refused too. Raise ValueError, which the route
        returns as 400.
        """
        breakdown = impact_request.options.get("breakdown")
        if breakdown is None:
            return
        if breakdown != LOCAL_AREA_BREAKDOWN:
            msg = f"Unknown breakdown: {breakdown!r}"
            raise ValueError(msg)
        if impact_request.country_id != "uk":
            msg = "breakdown=local_areas is only available for UK economy calculations"
            raise ValueError(msg)
        region = impact_request.region
        if region not in LOCAL_AREA_BREAKDOWN_REGIONS:
            msg = (
                "breakdown=local_areas needs region uk or a UK country, one of "
                f"{', '.join(LOCAL_AREA_BREAKDOWN_REGIONS)}; not {region!r}"
            )
            raise ValueError(msg)
        if impact_request.target == "cliff":
            msg = "breakdown=local_areas cannot be combined with target=cliff"
            raise ValueError(msg)

    @staticmethod
    def _validate_uk_region(impact_request: EconomicImpactRequest) -> None:
        """Reject a UK region the simulation service cannot resolve.

        Check the region the payload sends against the regions .py's UK region
        registry holds, using the UK metadata's lists (see
        ``policyengine_api.data.uk_regions``) and the simulation service's
        normalisation, so names, lower-case codes and bare country names keep
        working. Raise ValueError, which the route returns as 400, before
        anything is stored or submitted. Other countries are unchanged.
        """
        if impact_request.country_id != "uk":
            return
        region = impact_request.region
        if resolve_uk_region(region) is not None:
            return
        accepted = describe_accepted_uk_regions()
        msg = f"Unknown UK region {region!r}. Accepted regions: {accepted}."
        raise ValueError(msg)

    def _breakdown_refusal(
        self,
        error: httpx.HTTPStatusError,
        *,
        breakdown: LocalAreaBreakdown | None,
    ) -> EconomicImpactResult | None:
        """Return an error result when the simulation API refuses a breakdown.

        This API checks a breakdown request before submitting it, so a 400 or
        422 means the deployed simulation API, or the .py release it routes to,
        cannot run breakdowns yet. The route returns the result as 502 with the
        simulation API's reason. Nothing is stored, so a later request submits
        again and succeeds once the simulation API can run it.

        Return None for any other status, and for every request without a
        breakdown, so the caller re-raises those errors unchanged.
        """
        status_code = error.response.status_code
        if (
            breakdown is None
            or status_code not in LOCAL_AREA_BREAKDOWN_REFUSAL_STATUS_CODES
        ):
            return None
        return EconomicImpactResult.error(
            message=(
                "The simulation API refused the local-area breakdown request "
                f"(HTTP {status_code}): {self._build_submission_error_message(error)}"
            )
        )

    @staticmethod
    def _validation_field_reasons(details: object) -> str | None:
        """Join each ``loc: msg`` of a request-validation ``detail`` list."""
        if not isinstance(details, list):
            return None
        reasons = [
            ": ".join(
                part
                for part in (
                    ".".join(str(item) for item in detail.get("loc", [])),
                    str(detail.get("msg", "")),
                )
                if part
            )
            for detail in details
            if isinstance(detail, dict)
        ]
        return "; ".join(reason for reason in reasons if reason) or None

    def _build_submission_error_message(self, error: httpx.HTTPStatusError) -> str:
        """Return the reason in a simulation API refusal.

        A request-validation body (``detail`` as a list) names each field and
        its problem, without echoing the rejected input. Otherwise the first
        of ``detail``, ``message`` or ``error``, then the response text, then
        the exception text.
        """
        try:
            response_json = error.response.json()
        except ValueError:
            response_json = None

        if isinstance(response_json, dict):
            field_reasons = self._validation_field_reasons(response_json.get("detail"))
            if field_reasons:
                return field_reasons
            for key in ("detail", "message", "error"):
                value = response_json.get(key)
                if value:
                    return str(value)

        response_text = error.response.text.strip()
        if response_text:
            return response_text

        return str(error)

    def _setup_sim_options(
        self,
        setup_options: EconomicImpactSetupOptions,
        *,
        reform_policy: dict[str, Any] | str,
        baseline_policy: dict[str, Any] | str,
        time_period: str | int,
        include_cliffs: bool = False,
    ) -> SimulationOptions:
        """Set up the macro simulation options for one simulation API job."""
        return SimulationOptions.model_validate(
            {
                "country": setup_options.country_id,
                "spm": setup_options.options.get("spm"),
                "scope": "macro",
                "reform": self._parse_json_object(reform_policy),
                "baseline": self._parse_json_object(baseline_policy),
                "time_period": time_period,
                "include_cliffs": include_cliffs,
                "region": self._setup_region(
                    country_id=setup_options.country_id, region=setup_options.region
                ),
                "model_version": setup_options.model_version,
                "policyengine_version": setup_options.policyengine_version,
                "breakdown": setup_options.options.get("breakdown"),
            }
        )

    def _setup_region(self, country_id: str, region: str) -> str:
        """Validate the region and return the code the simulation API expects.

        Assumes region has already been normalized (e.g., "ca" -> "state/ca").
        Raises ValueError for invalid regions. A UK region is sent as
        requested: request setup has already checked it against .py's UK
        region registry.
        """
        # For US regions, validate (skip validation for national "us")
        if country_id == "us" and region != "us":
            self._validate_us_region(region)

        return region

    def _validate_us_region(self, region: str) -> None:
        """Validate a prefixed US region string.

        Raises ValueError if the region is not valid.
        """
        if region.startswith("state/"):
            state_code = region[len("state/") :]
            if state_code.lower() not in get_valid_state_codes():
                msg = f"Invalid US state: '{state_code}'"
                raise ValueError(msg)
        elif region.startswith("place/"):
            place_code = region[len("place/") :]
            validate_place_code(place_code)
        elif region.startswith("congressional_district/"):
            district_id = region[len("congressional_district/") :]
            if district_id.lower() not in get_valid_congressional_districts():
                msg = f"Invalid congressional district: '{district_id}'"
                raise ValueError(msg)
        else:
            msg = f"Invalid US region: '{region}'"
            raise ValueError(msg)

    def _build_simulation_telemetry(
        self,
        setup_options: EconomicImpactSetupOptions,
        sim_config: dict[str, Any],
    ) -> dict[str, Any]:
        simulation_kind, geography_type, geography_code = (
            self._classify_simulation_geography(
                country_id=setup_options.country_id,
                region=setup_options.region,
            )
        )
        if setup_options.options.get("breakdown") is not None:
            simulation_kind = LOCAL_AREA_BREAKDOWN_SIMULATION_KIND

        return {
            "submission_claim_id": setup_options.submission_claim_id,
            "requested_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "simulation_kind": simulation_kind,
            "geography_code": geography_code,
            "geography_type": geography_type,
            "config_hash": self._stable_config_hash(sim_config),
            "capture_mode": "disabled",
        }

    def _classify_simulation_geography(
        self,
        country_id: str,
        region: str,
    ) -> tuple[str, str, str]:
        if region == country_id:
            return "national", "national", country_id

        if "/" not in region:
            return "other", "other", region

        geography_type, geography_code = region.split("/", maxsplit=1)
        simulation_kind = (
            "district" if geography_type == "congressional_district" else geography_type
        )
        return simulation_kind, geography_type, geography_code

    def _stable_config_hash(self, payload: dict[str, Any]) -> str:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

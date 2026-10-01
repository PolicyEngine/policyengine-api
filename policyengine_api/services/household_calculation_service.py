from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import date
import time
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS, POLICYENGINE_VERSION
from policyengine_api.observability import runtime as observability_runtime
from policyengine_api.observability.stages import HOUSEHOLD_STAGES, Stage
from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import (
    Household,
    Policy,
)
from policyengine_api.runtime_cache.dependencies import get_runtime_cache_context
from policyengine_api.runtime_cache.core import record_cache_event
from policyengine_api.runtime_cache.household_calculations import (
    CachedHouseholdCalculation,
    HouseholdCalculationCache,
    HouseholdCalculationIdentity,
)
from policyengine_api.utils.deprecated_inputs import drop_deprecated_inputs
from policyengine_api.utils.input_validation import find_unrecognized_inputs
from policyengine_api.spm import (
    normalize_spm_selection,
    validate_spm_calculation_provenance,
)


@dataclass(frozen=True)
class CalculationResult:
    household: dict
    warnings: tuple[str, ...] = ()
    spm_config: dict | None = None
    spm_provenance: dict | None = None


@dataclass(frozen=True)
class HouseholdCalculationResult:
    household: dict
    warnings: tuple[str, ...] = ()
    cached: bool = False
    spm_config: dict | None = None
    spm_provenance: dict | None = None


@dataclass(frozen=True)
class PreparedHouseholdCalculation:
    """Validated request inputs ready for calculation after cache lookup."""

    country: Any
    household_json: dict
    policy_json: dict
    spm: dict | None
    spm_requested: bool
    warnings: tuple[str, ...]
    country_calculation: Any | None = None


class HouseholdNotFoundError(LookupError):
    pass


class PolicyNotFoundError(LookupError):
    pass


class InvalidHouseholdInputsError(ValueError):
    def __init__(self, invalid_inputs: list[Any]) -> None:
        self.invalid_inputs = invalid_inputs
        super().__init__("Household or policy contains unrecognized inputs")


def _validated_spm_fields(
    spm_config: object,
    spm_provenance: object,
    expected_selection: dict | None,
) -> tuple[dict | None, dict | None]:
    if expected_selection is None:
        if spm_config is None and spm_provenance is None:
            return None, None
        raise ValueError("Unexpected SPM provenance for a calculation without SPM")
    calculation = validate_spm_calculation_provenance(
        spm_config,
        spm_provenance,
    )
    canonical_config = calculation.spm_config.model_dump(mode="json")
    if canonical_config != expected_selection:
        raise ValueError("SPM calculation configuration differs from the request")
    return (
        canonical_config,
        calculation.spm_provenance.model_dump(mode="json", by_alias=True),
    )


def get_household_year(household: dict) -> int | str:
    household_year: int | str = date.today().year
    household_age_list = list(
        household.get("people", {}).get("you", {}).get("age", {}).keys()
    )
    if household_age_list:
        household_year = household_age_list[0]
    return household_year


def add_yearly_variables(
    household: dict,
    country_id: str,
    countries: dict | None = None,
) -> dict:
    if countries is None:
        from policyengine_api.country import COUNTRIES

        countries = COUNTRIES
    metadata = countries.get(country_id).metadata
    variables = metadata["variables"]
    entities = metadata["entities"]
    household_year = get_household_year(household)

    for variable in variables.values():
        if variable["definitionPeriod"] not in ("year", "month", "eternity"):
            continue
        entity_plural = entities[variable["entity"]]["plural"]
        for entity in household.get(entity_plural, {}).values():
            if variable["name"] not in entity:
                entity[variable["name"]] = {
                    household_year: (
                        variable["defaultValue"]
                        if variable["isInputVariable"]
                        else None
                    )
                }
    return household


class HouseholdCalculationService:
    """Orchestrate stored-household calculations with short DB scopes."""

    def __init__(
        self,
        primary_session_factory: sessionmaker[Session] | None = None,
        cache: HouseholdCalculationCache | None = None,
        country_provider: Callable[[], dict] | None = None,
    ) -> None:
        self._injected_primary_session_factory = primary_session_factory
        if cache is None:
            context = get_runtime_cache_context()
            cache = HouseholdCalculationCache(context.client, context.namespace)
        self._cache = cache
        self._country_provider = country_provider

    @property
    def _primary_sessions(self) -> sessionmaker[Session]:
        return self._injected_primary_session_factory or get_v1_session_factory()

    def _countries(self) -> dict:
        if self._country_provider is not None:
            return self._country_provider()
        from policyengine_api.country import COUNTRIES

        return COUNTRIES

    @staticmethod
    def _cache_identity(
        country_id: str,
        household: Household,
        policy: Policy,
        api_version: str,
        spm: dict | None = None,
    ) -> HouseholdCalculationIdentity:
        return HouseholdCalculationIdentity(
            country_id=country_id,
            household_id=household.id,
            policy_id=policy.id,
            household_hash=household.household_hash,
            policy_hash=policy.policy_hash,
            country_package_version=api_version,
            policyengine_version=POLICYENGINE_VERSION,
            spm=spm,
        )

    def _get_inputs(
        self,
        country_id: str,
        household_id: int,
        policy_id: int,
    ) -> tuple[Household | None, Policy | None]:
        with self._primary_sessions() as session:
            household = session.scalar(
                select(Household).where(
                    Household.country_id == country_id,
                    Household.id == household_id,
                )
            )
            policy = session.scalar(
                select(Policy).where(
                    Policy.country_id == country_id,
                    Policy.id == policy_id,
                )
            )
            return household, policy

    @observability_runtime.span(HOUSEHOLD_STAGES.name(Stage.HOUSEHOLD_CACHE_WRITE))
    def _store_result(
        self,
        identity: HouseholdCalculationIdentity,
        calculation: CalculationResult,
        warnings: tuple[str, ...],
    ) -> None:
        self._cache.set(
            identity,
            CachedHouseholdCalculation(
                household=calculation.household,
                warnings=warnings,
                spm_config=calculation.spm_config,
                spm_provenance=calculation.spm_provenance,
            ),
        )

    def calculate_stored_household(
        self,
        country_id: str,
        household_id: int,
        policy_id: int,
        *,
        on_accepted: Callable[[], object] | None = None,
    ) -> HouseholdCalculationResult:
        api_version = COUNTRY_PACKAGE_VERSIONS[country_id]
        with observability_runtime.span(
            HOUSEHOLD_STAGES.name(Stage.HOUSEHOLD_LOAD_INPUTS)
        ):
            household, policy = self._get_inputs(
                country_id,
                household_id,
                policy_id,
            )
            if household is None:
                raise HouseholdNotFoundError(household_id)
            if policy is None:
                raise PolicyNotFoundError(policy_id)
            household_inputs = deepcopy(household.household_json)
            # A household saved without a selection never chose a measurement,
            # so its replay keeps the historical output set rather than failing
            # closed.
            saved_spm = household_inputs.pop("spm", None)
            spm = normalize_spm_selection(country_id, saved_spm, stored=True)
            if on_accepted is not None:
                # Bind before this stage ends so its span carries the same
                # identifier as the cache and calculation stages that follow.
                on_accepted()
        cache_identity = self._cache_identity(
            country_id,
            household,
            policy,
            api_version,
            spm,
        )
        with observability_runtime.span(
            HOUSEHOLD_STAGES.name(Stage.HOUSEHOLD_CACHE_LOOKUP)
        ):
            cached = self._cache.get(cache_identity)
        if cached is not None:
            return HouseholdCalculationResult(
                household=cached.household,
                warnings=cached.warnings,
                cached=True,
                spm_config=cached.spm_config,
                spm_provenance=cached.spm_provenance,
            )

        with observability_runtime.span(
            HOUSEHOLD_STAGES.name(Stage.HOUSEHOLD_INPUT_NORMALIZATION)
        ):
            countries = self._countries()
            country = countries.get(country_id)
            household_json = add_yearly_variables(
                household_inputs,
                country_id,
                countries,
            )
            deprecated_inputs = drop_deprecated_inputs(household_json)
            household_json = deprecated_inputs.household
            invalid_inputs = find_unrecognized_inputs(
                household_json,
                policy.policy_json,
                country.metadata,
            )
        if invalid_inputs:
            raise InvalidHouseholdInputsError(invalid_inputs)

        calculation_started_at = time.perf_counter()
        try:
            with observability_runtime.span(
                HOUSEHOLD_STAGES.name(Stage.HOUSEHOLD_CALCULATION)
            ):
                raw_calculation = country.calculate(
                    household_json,
                    policy.policy_json,
                    **(
                        {"spm": spm, "spm_requested": saved_spm is not None}
                        if spm is not None
                        else {}
                    ),
                )
        except Exception:
            record_cache_event(
                family="household-calculation",
                event="recompute-failed",
                started_at=calculation_started_at,
                severity="WARNING",
            )
            raise
        if isinstance(raw_calculation, CalculationResult):
            calculation = raw_calculation
        elif hasattr(raw_calculation, "household"):
            calculation = CalculationResult(
                household=raw_calculation.household,
                warnings=tuple(getattr(raw_calculation, "warnings", ())),
                spm_config=getattr(raw_calculation, "spm_config", None),
                spm_provenance=getattr(raw_calculation, "spm_provenance", None),
            )
        else:
            # Temporary compatibility for test doubles and country packages
            # that have not yet adopted CalculationResult.
            calculation = CalculationResult(
                household=raw_calculation,
            )
        spm_config, spm_provenance = _validated_spm_fields(
            calculation.spm_config,
            calculation.spm_provenance,
            spm,
        )
        calculation = replace(
            calculation,
            spm_config=spm_config,
            spm_provenance=spm_provenance,
        )
        record_cache_event(
            family="household-calculation",
            event="recompute",
            started_at=calculation_started_at,
        )
        response_warnings = (
            tuple(warning.message for warning in deprecated_inputs.warnings)
            + calculation.warnings
        )
        self._store_result(
            cache_identity,
            calculation,
            response_warnings,
        )
        return HouseholdCalculationResult(
            household=calculation.household,
            warnings=response_warnings,
            spm_config=calculation.spm_config,
            spm_provenance=calculation.spm_provenance,
        )

    def prepare_household_calculation(
        self,
        country_id: str,
        household_json: dict,
        policy_json: dict,
        *,
        add_missing: bool = False,
        spm: dict | None = None,
        spm_requested: bool = False,
    ) -> PreparedHouseholdCalculation:
        """Validate request inputs before accepting a calculation."""

        countries = self._countries()
        country = countries.get(country_id)
        spm = normalize_spm_selection(country_id, spm)
        household_json = deepcopy(household_json)
        if add_missing:
            household_json = add_yearly_variables(
                household_json,
                country_id,
                countries,
            )

        deprecated_inputs = drop_deprecated_inputs(household_json)
        household_json = deprecated_inputs.household
        invalid_inputs = find_unrecognized_inputs(
            household_json,
            policy_json,
            country.metadata,
        )
        if invalid_inputs:
            raise InvalidHouseholdInputsError(invalid_inputs)

        return PreparedHouseholdCalculation(
            country=country,
            household_json=household_json,
            policy_json=policy_json,
            spm=spm,
            spm_requested=spm_requested,
            warnings=tuple(warning.message for warning in deprecated_inputs.warnings),
        )

    def calculate_prepared_household(
        self,
        prepared: PreparedHouseholdCalculation,
    ) -> HouseholdCalculationResult:
        """Calculate inputs already accepted by ``prepare_household_calculation``."""

        with observability_runtime.span(
            HOUSEHOLD_STAGES.name(Stage.HOUSEHOLD_CALCULATION)
        ):
            calculation_options = (
                {
                    "spm": prepared.spm,
                    "spm_requested": prepared.spm_requested,
                }
                if prepared.spm is not None
                else {}
            )
            if prepared.country_calculation is not None:
                calculation_options["prepared"] = prepared.country_calculation
            raw_calculation = prepared.country.calculate(
                prepared.household_json,
                prepared.policy_json,
                **calculation_options,
            )
        if isinstance(raw_calculation, dict):
            household = raw_calculation
            calculation_warnings = ()
        else:
            household = raw_calculation.household
            calculation_warnings = tuple(getattr(raw_calculation, "warnings", ()))
        spm_config, spm_provenance = _validated_spm_fields(
            getattr(raw_calculation, "spm_config", None),
            getattr(raw_calculation, "spm_provenance", None),
            prepared.spm,
        )
        return HouseholdCalculationResult(
            household=household,
            warnings=(prepared.warnings + calculation_warnings),
            spm_config=spm_config,
            spm_provenance=spm_provenance,
        )

    @observability_runtime.span(
        HOUSEHOLD_STAGES.name(Stage.HOUSEHOLD_INPUT_NORMALIZATION)
    )
    def parse_prepared_household(
        self,
        prepared: PreparedHouseholdCalculation,
        *,
        on_accepted: Callable[[], object] | None = None,
    ) -> PreparedHouseholdCalculation:
        """Parse a prepared situation without performing requested calculations."""

        prepare_calculation = getattr(prepared.country, "prepare_calculation", None)
        country_calculation = prepared.country_calculation
        if callable(prepare_calculation):
            country_calculation = prepare_calculation(
                prepared.household_json,
                prepared.policy_json,
                **(
                    {
                        "spm": prepared.spm,
                        "spm_requested": prepared.spm_requested,
                    }
                    if prepared.spm is not None
                    else {}
                ),
            )
        if on_accepted is not None:
            # Situation parsing succeeded. Bind before this stage span ends so
            # it participates in the accepted calculation's identifier query.
            on_accepted()
        return replace(prepared, country_calculation=country_calculation)

    def calculate_household(
        self,
        country_id: str,
        household_json: dict,
        policy_json: dict,
        *,
        add_missing: bool = False,
        spm: dict | None = None,
        spm_requested: bool = False,
    ) -> HouseholdCalculationResult:
        """Validate and calculate request-provided household and policy data."""

        prepared = self.prepare_household_calculation(
            country_id,
            household_json,
            policy_json,
            add_missing=add_missing,
            spm=spm,
            spm_requested=spm_requested,
        )
        return self.calculate_prepared_household(prepared)

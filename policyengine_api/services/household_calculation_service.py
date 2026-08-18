from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date
import time
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from policyengine_api.constants import COUNTRY_PACKAGE_VERSIONS, POLICYENGINE_VERSION
from policyengine_api.data.orm import get_v1_session_factory
from policyengine_api.data.v1_models import (
    Household,
    Policy,
)
from policyengine_api.runtime_cache.dependencies import get_runtime_cache_context
from policyengine_api.runtime_cache.core import record_cache_event
from policyengine_api.runtime_cache.repositories import (
    HouseholdTraceCache,
    HouseholdTraceIdentity,
    HouseholdTraceValue,
)
from policyengine_api.utils.deprecated_inputs import drop_deprecated_inputs
from policyengine_api.utils.input_validation import find_unrecognized_inputs


@dataclass(frozen=True)
class CalculationResult:
    household: dict
    tracer_output: list[str]


@dataclass(frozen=True)
class HouseholdCalculationResult:
    household: dict
    warnings: tuple[str, ...] = ()
    cached: bool = False


class HouseholdNotFoundError(LookupError):
    pass


class PolicyNotFoundError(LookupError):
    pass


class InvalidHouseholdInputsError(ValueError):
    def __init__(self, invalid_inputs: list[Any]) -> None:
        self.invalid_inputs = invalid_inputs
        super().__init__("Household or policy contains unrecognized inputs")


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
        cache: HouseholdTraceCache | None = None,
        country_provider: Callable[[], dict] | None = None,
    ) -> None:
        self._injected_primary_session_factory = primary_session_factory
        if cache is None:
            context = get_runtime_cache_context()
            cache = HouseholdTraceCache(context.client, context.namespace)
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
    ) -> HouseholdTraceIdentity:
        return HouseholdTraceIdentity(
            country_id=country_id,
            household_id=household.id,
            policy_id=policy.id,
            household_hash=household.household_hash,
            policy_hash=policy.policy_hash,
            country_package_version=api_version,
            policyengine_version=POLICYENGINE_VERSION,
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

    def _store_result(
        self,
        identity: HouseholdTraceIdentity,
        calculation: CalculationResult,
    ) -> None:
        self._cache.set(
            identity,
            HouseholdTraceValue(
                household=calculation.household,
                tracer_output=calculation.tracer_output,
            ),
        )

    def calculate_stored_household(
        self,
        country_id: str,
        household_id: int,
        policy_id: int,
    ) -> HouseholdCalculationResult:
        api_version = COUNTRY_PACKAGE_VERSIONS[country_id]
        household, policy = self._get_inputs(country_id, household_id, policy_id)
        if household is None:
            raise HouseholdNotFoundError(household_id)
        if policy is None:
            raise PolicyNotFoundError(policy_id)
        cache_identity = self._cache_identity(
            country_id,
            household,
            policy,
            api_version,
        )
        cached = self._cache.get(cache_identity)
        if cached is not None:
            return HouseholdCalculationResult(
                household=cached.household,
                cached=True,
            )

        countries = self._countries()
        country = countries.get(country_id)
        household_json = add_yearly_variables(
            deepcopy(household.household_json),
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
            raw_calculation = country.calculate(household_json, policy.policy_json)
        except Exception:
            record_cache_event(
                family="household-trace",
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
                tracer_output=raw_calculation.tracer_output,
            )
        else:
            # Temporary compatibility for test doubles and country packages
            # that have not yet adopted CalculationResult.
            calculation = CalculationResult(
                household=raw_calculation,
                tracer_output=[],
            )
        record_cache_event(
            family="household-trace",
            event="recompute",
            started_at=calculation_started_at,
        )
        self._store_result(
            cache_identity,
            calculation,
        )
        return HouseholdCalculationResult(
            household=calculation.household,
            warnings=tuple(warning.message for warning in deprecated_inputs.warnings),
        )

    def calculate_household(
        self,
        country_id: str,
        household_json: dict,
        policy_json: dict,
        *,
        add_missing: bool = False,
    ) -> HouseholdCalculationResult:
        """Validate and calculate request-provided household and policy data."""
        countries = self._countries()
        country = countries.get(country_id)
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

        raw_calculation = country.calculate(household_json, policy_json)
        household = (
            raw_calculation
            if isinstance(raw_calculation, dict)
            else raw_calculation.household
        )
        return HouseholdCalculationResult(
            household=household,
            warnings=tuple(warning.message for warning in deprecated_inputs.warnings),
        )

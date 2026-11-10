"""Checks of a household calculation against values already loaded."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from policyengine_api.services.v2.household_calculations.types import (
    StoredExecutionFailure,
    StoredExecutionResult,
)

if TYPE_CHECKING:
    from collections.abc import Iterable
    from uuid import UUID

    from policyengine_api.services.v2.countries.types import CountryRead


class HouseholdCalculationCountryError(ValueError):
    """The country does not offer household calculations."""


class HouseholdCalculationYearError(ValueError):
    """The household has no default year to calculate."""


class HouseholdCalculationNotFoundError(LookupError):
    """household_jobs has no job with this ID."""


class HouseholdCalculationResultUnreadableError(RuntimeError):
    """A succeeded job's stored result is not one result document the API reads."""


class HouseholdCalculationStorageError(RuntimeError):
    """The v2 database could not be read while handling a household calculation."""


def require_household_country(
    countries: Iterable[CountryRead], country_id: str
) -> None:
    """Raise HouseholdCalculationCountryError unless the country calculates households.

    A household-only country (household calculations without society-wide
    reports) passes; a country without a ``countries`` row does not.
    """
    for country in countries:
        if country.id == country_id and country.household_enabled:
            return
    msg = f"Household calculations are not available for country {country_id}."
    raise HouseholdCalculationCountryError(msg)


def require_default_year(default_year: int | None) -> None:
    """Raise HouseholdCalculationYearError unless the household has a default year.

    The simulation service calculates that year, the year the household's
    values name.
    """
    if default_year is None:
        msg = "This household has no default year to calculate."
        raise HouseholdCalculationYearError(msg)


def stored_household_outcome(
    job_id: UUID, status: str, document: object
) -> StoredExecutionResult | StoredExecutionFailure | None:
    """Return a job's stored result document, read as its status says.

    An unfinished job's result is not read. A succeeded job must hold one
    ``HouseholdExecutionResult`` with exactly one policy result, or
    HouseholdCalculationResultUnreadableError is raised. A failed job holds a
    ``HouseholdExecutionFailure``, or None when it failed without one; any
    other document is read as none, since the job's error message still
    says why it failed.
    """
    if status == "succeeded":
        try:
            return StoredExecutionResult.model_validate(document)
        except ValidationError as error:
            msg = f"Household calculation {job_id} has an unreadable result."
            raise HouseholdCalculationResultUnreadableError(msg) from error
    if status == "failed" and document is not None:
        try:
            return StoredExecutionFailure.model_validate(document)
        except ValidationError:
            return None
    return None

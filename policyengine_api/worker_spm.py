"""Canonical economy execution requires the selected worker's certified capability."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from policyengine_api.spm import (
    SPMComparisonProvenance,
    SPMSelection,
    SPMValidationError,
    error_message,
    normalize_spm_selection,
    resolved_spm_configuration,
    validate_spm_calculation_provenance,
)

if TYPE_CHECKING:
    import httpx


class SPMCapabilitySource(Protocol):
    """A worker registry that reports its certified canonical SPM capability."""

    def get_spm_capability(
        self,
        country: str,
        model_version: str | None,
        /,
        *,
        policyengine_version: str | None,
    ) -> object:
        """Return the worker's SPM capability document, or None if it has none."""
        ...


def validate_worker_spm(
    country_id: str,
    selection: object = None,
    *,
    gateway: SPMCapabilitySource | None = None,
    policyengine_version: str | None = None,
    model_version: str | None = None,
) -> dict | None:
    """Resolve an SPM selection and confirm the selected worker can execute it.

    Return the resolved selection, or None for a country without SPM support.
    Raise SPMValidationError (SPM_CONFIGURATION_UNAVAILABLE)
    when the worker advertises no canonical SPM capability, a different
    contract, or a different forecast artifact from the API's.
    """
    country_id = country_id.lower() if isinstance(country_id, str) else country_id
    resolved = normalize_spm_selection(country_id, selection)
    if resolved is None:
        return None
    capability = None
    if gateway is not None:
        capability = gateway.get_spm_capability(
            country_id, model_version, policyengine_version=policyengine_version
        )
    try:
        _check_worker_capability(capability, resolved)
    except ValueError as exc:
        msg = "SPM_CONFIGURATION_UNAVAILABLE"
        raise SPMValidationError(msg, error_message(exc)) from exc
    return resolved


def _check_worker_capability(capability: object, resolved: dict) -> None:
    """Raise ValueError unless the worker certifies the API's SPM artifact."""
    if not isinstance(capability, dict) or set(capability) != {
        "contract_version",
        "defaults",
    }:
        msg = "The selected worker has no certified canonical SPM capability"
        raise ValueError(msg)
    if capability["contract_version"] != "canonical-spm-v1":
        msg = "The selected worker uses an unsupported SPM contract"
        raise ValueError(msg)
    defaults = SPMSelection.model_validate(capability["defaults"])
    if not defaults.scenario or not defaults.forecast_content_sha256:
        msg = "The worker capability must pin SPM artifact hash and scenario"
        raise ValueError(msg)
    if defaults.forecast_content_sha256 != resolved["forecast_content_sha256"]:
        msg = "The API and worker SPM artifact identities differ"
        raise ValueError(msg)


def validate_worker_result(
    result: dict,
    selection: dict | None,
    *,
    expected_year: str | int | None = None,
    expected_years: list[str] | None = None,
) -> None:
    """Check that a worker's economy result carries SPM receipts matching the request.

    An annual result must hold a comparison receipt whose baseline and reform
    resolve to ``selection`` and cover ``expected_year``; a budget-window result
    must have one valid annual result per requested year. Raise
    SPMValidationError (SPM_CONFIGURATION_UNAVAILABLE) on any mismatch. Do nothing
    when no selection was requested.
    """
    if selection is None:
        return
    try:
        _check_worker_result(
            result,
            selection,
            expected_year=expected_year,
            expected_years=expected_years,
        )
    except (ValueError, TypeError, KeyError) as exc:
        msg = "SPM_CONFIGURATION_UNAVAILABLE"
        raise SPMValidationError(msg, error_message(exc)) from exc


def _check_worker_result(
    result: dict,
    selection: dict,
    *,
    expected_year: str | int | None,
    expected_years: list[str] | None,
) -> None:
    """Raise TypeError, ValueError or KeyError unless the result's receipts match."""
    if not isinstance(result, dict):
        msg = "Worker SPM result must be an object"
        raise TypeError(msg)
    if result.get("kind") == "budgetWindow":
        if expected_year is not None:
            msg = "Expected an annual SPM result"
            raise ValueError(msg)
        rows = result.get("annualImpacts")
        size = result.get("windowSize")
        if type(size) is not int or size < 1:
            msg = "Budget window size must be a positive integer"
            raise ValueError(msg)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            msg = "Budget window annual impacts must be objects"
            raise ValueError(msg)
        if len(rows) != size:
            msg = "Budget window has incomplete SPM receipts"
            raise ValueError(msg)
        actual = [str(row.get("year")) for row in rows]
        if any(
            len(year) != 4 or not year.isascii() or not year.isdigit()
            for year in actual
        ):
            msg = "Budget window annual impacts require calendar years"
            raise ValueError(msg)
        if len(set(actual)) != len(actual):
            msg = "Budget window SPM result years differ from request"
            raise ValueError(msg)
        if expected_years is not None:
            wanted = [str(year) for year in expected_years]
            if actual != wanted:
                msg = "Budget window SPM result years differ from request"
                raise ValueError(msg)
        for row in rows:
            validate_worker_result(row, selection, expected_year=row.get("year"))
        return
    if expected_years is not None:
        msg = "Expected a budget window SPM result"
        raise ValueError(msg)
    if "spm_config" in result:
        msg = "Worker result must not include legacy spm_config"
        raise ValueError(msg)
    comparison = SPMComparisonProvenance.model_validate(result.get("spm_provenance"))
    for side in ("baseline", "reform"):
        execution = getattr(comparison, side)
        receipt = validate_spm_calculation_provenance(execution.receipt)
        resolved = resolved_spm_configuration(receipt).model_dump(mode="json")
        if resolved != selection:
            msg = "Worker result SPM settings differ from the request"
            raise ValueError(msg)
        if expected_year is not None and str(expected_year) not in receipt.years:
            msg = "Worker SPM receipt does not cover requested year"
            raise ValueError(msg)


def raise_worker_spm_error(response: httpx.Response) -> None:
    """Preserve public typed input errors across asynchronous HTTP polling."""
    if response.status_code not in (400, 422):
        return
    try:
        errors = response.json().get("errors", [])
    except (ValueError, AttributeError):
        return
    for error in errors:
        if (
            isinstance(error, dict)
            and error.get("code")
            in {
                "SPM_GEOGRAPHY_REQUIRED",
                "SPM_GEOGRAPHY_UNAVAILABLE",
                "SPM_COMPOSITION_REQUIRED",
                "SPM_YEAR_UNAVAILABLE",
                "SPM_SETTINGS_INVALID",
                "SPM_SETTINGS_UNSUPPORTED",
                "SPM_CONFIGURATION_UNAVAILABLE",
            }
            and isinstance(error.get("message"), str)
        ):
            raise SPMValidationError(error["code"], error["message"])

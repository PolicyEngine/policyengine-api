"""Canonical economy execution requires the selected worker's certified capability."""

from policyengine_api.spm import (
    SPMSelection,
    SPMProvenance,
    SPMValidationError,
    normalize_spm_selection,
    resolved_spm_settings,
)


def validate_worker_spm(
    country_id: str,
    selection: object = None,
    *,
    gateway=None,
    policyengine_version=None,
    model_version=None,
) -> dict | None:
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
        if not isinstance(capability, dict) or set(capability) != {
            "contract_version",
            "defaults",
        }:
            raise ValueError(
                "The selected worker has no certified canonical SPM capability"
            )
        if capability["contract_version"] != "canonical-spm-v1":
            raise ValueError("The selected worker uses an unsupported SPM contract")
        defaults = SPMSelection.model_validate(capability["defaults"])
        if not defaults.scenario or not defaults.forecast_content_sha256:
            raise ValueError(
                "The worker capability must pin SPM artifact hash and scenario"
            )
        if defaults.forecast_content_sha256 != resolved["forecast_content_sha256"]:
            raise ValueError("The API and worker SPM artifact identities differ")
    except ValueError as exc:
        raise SPMValidationError("SPM_CONFIGURATION_UNAVAILABLE", str(exc)) from exc
    return resolved


def validate_worker_result(
    result: dict,
    selection: dict | None,
    *,
    expected_year: str | int | None = None,
    expected_years: list[str] | None = None,
) -> None:
    if selection is None:
        return
    try:
        if not isinstance(result, dict):
            raise ValueError("Worker SPM result must be an object")
        if result.get("kind") == "budgetWindow":
            if expected_year is not None:
                raise ValueError("Expected an annual SPM result")
            rows = result.get("annualImpacts")
            size = result.get("windowSize")
            if type(size) is not int or size < 1:
                raise ValueError("Budget window size must be a positive integer")
            if not isinstance(rows, list) or not all(
                isinstance(row, dict) for row in rows
            ):
                raise ValueError("Budget window annual impacts must be objects")
            if len(rows) != size:
                raise ValueError("Budget window has incomplete SPM receipts")
            actual = [str(row.get("year")) for row in rows]
            if any(
                len(year) != 4 or not year.isascii() or not year.isdigit()
                for year in actual
            ):
                raise ValueError("Budget window annual impacts require calendar years")
            if len(set(actual)) != len(actual):
                raise ValueError("Budget window SPM result years differ from request")
            if expected_years is not None:
                wanted = [str(year) for year in expected_years]
                if actual != wanted:
                    raise ValueError(
                        "Budget window SPM result years differ from request"
                    )
            for row in rows:
                validate_worker_result(row, selection, expected_year=row.get("year"))
            return
        if expected_years is not None:
            raise ValueError("Expected a budget window SPM result")
        resolved = resolved_spm_settings(result.get("spm_config"))
        if resolved is None:
            raise ValueError("Worker result has incomplete resolved SPM settings")
        if resolved != selection:
            raise ValueError("Worker result SPM settings differ from the request")
        receipts = result.get("spm_provenance")
        if not isinstance(receipts, dict) or set(receipts) != {"baseline", "reform"}:
            raise ValueError("Worker result has no baseline/reform SPM receipts")
        for side in ("baseline", "reform"):
            if not isinstance(receipts[side], list) or not receipts[side]:
                raise ValueError("Worker result has an empty SPM receipt")
            for item in receipts[side]:
                receipt = SPMProvenance.model_validate(item)
                if (
                    expected_year is not None
                    and str(expected_year) not in receipt.years
                ):
                    raise ValueError("Worker SPM receipt does not cover requested year")
                if (
                    receipt.forecast_sha256 != selection["forecast_content_sha256"]
                    or receipt.scenario != selection["scenario"]
                    or receipt.geography_kind != selection["geography_kind"]
                ):
                    raise ValueError(
                        "Worker result SPM provenance differs from the request"
                    )
    except (ValueError, TypeError, KeyError) as exc:
        raise SPMValidationError("SPM_CONFIGURATION_UNAVAILABLE", str(exc)) from exc


def raise_worker_spm_error(response) -> None:
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

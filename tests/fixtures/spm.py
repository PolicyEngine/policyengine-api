"""Shared result shapes for the SPM behavior selected by the installed bundle."""

from __future__ import annotations

from policyengine_api import spm
from policyengine_api.constants import POLICYENGINE_VERSION


SPM_CONTRACT_VERSION = "canonical-spm-v1"
INSTALLED_SPM_SELECTION = spm.normalize_spm_selection("us", None)


def worker_spm_capability(selection: dict | None = None) -> dict | None:
    """Return the capability advertised by a worker using this bundle."""
    resolved = INSTALLED_SPM_SELECTION if selection is None else selection
    if resolved is None:
        return None
    return {
        "contract_version": SPM_CONTRACT_VERSION,
        "defaults": dict(resolved),
    }


def worker_versions_document(
    *,
    bundle_version: str = POLICYENGINE_VERSION,
    app_name: str = "test-worker-app",
    country: str = "us",
    country_version: str | None = None,
    selection: dict | None = None,
) -> dict:
    """Return the gateway registry document for a matching test worker."""
    document: dict = {
        "policyengine": {bundle_version: app_name, "latest": bundle_version},
    }
    if country_version is not None:
        document[country] = {
            country_version: app_name,
            "latest": country_version,
        }
    capability = worker_spm_capability(selection)
    if capability is not None:
        document["spm_capabilities"] = {bundle_version: capability}
    return document


def spm_receipt(*, years, selection: dict | None = None) -> dict:
    """Return one calculation receipt covering the supplied years."""
    resolved = INSTALLED_SPM_SELECTION if selection is None else selection
    if resolved is None:
        raise ValueError("An SPM receipt requires a resolved selection")
    return {
        "schema_version": "canonical-spm-provenance-v2",
        "forecast_id": "test-only",
        "forecast_sha256": resolved["forecast_content_sha256"],
        "scenario": resolved["scenario"],
        "geography_kind": resolved["geography_kind"],
        "geography_id": resolved["geography_id"],
        "county_vintage": resolved["county_vintage"],
        "as_of": resolved["as_of"],
        "years": sorted({str(year) for year in years}),
        "runtime_versions": {
            "policyengine": "test-only",
            "policyengine-core": "test-only",
            "policyengine-us": "test-only",
            "spm-calculator": "test-only",
        },
    }


def worker_result_fields(*, years, selection: dict | None = None) -> dict:
    """Return the SPM fields required on an economy worker result."""
    resolved = INSTALLED_SPM_SELECTION if selection is None else selection
    if resolved is None:
        return {}
    receipt = spm_receipt(years=years, selection=resolved)
    return {
        "spm_provenance": {
            "schema_version": "canonical-spm-comparison-v2",
            "baseline": {
                "receipt": dict(receipt),
                "execution_count": 1,
            },
            "reform": {
                "receipt": dict(receipt),
                "execution_count": 1,
            },
        },
    }


def household_result_fields(*, years, selection: dict | None = None) -> dict:
    """Return the SPM fields required on a household calculation result."""
    resolved = INSTALLED_SPM_SELECTION if selection is None else selection
    if resolved is None:
        return {}
    return {
        "spm_provenance": spm_receipt(years=years, selection=resolved),
    }


def resolved_options(options: dict, selection: dict | None = None) -> dict:
    """Return request options after applying the installed bundle default."""
    resolved = INSTALLED_SPM_SELECTION if selection is None else selection
    if resolved is None:
        return dict(options)
    return {**options, "spm": dict(resolved)}


def options_hash_segment(selection: dict | None = None) -> str:
    """Return the part of a sorted options hash contributed by SPM."""
    resolved = INSTALLED_SPM_SELECTION if selection is None else selection
    return "" if resolved is None else f"&spm={resolved}"


def provenance_schema_hash_segment(selection: dict | None = None) -> str:
    """Return the cache-identity segment for compact society-wide receipts."""
    resolved = INSTALLED_SPM_SELECTION if selection is None else selection
    if resolved is None:
        return ""
    return "&spm_provenance_schema=canonical-spm-comparison-v2"

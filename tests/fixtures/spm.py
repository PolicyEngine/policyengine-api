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
        "forecast_id": "test-only",
        "forecast_sha256": resolved["forecast_content_sha256"],
        "scenario": resolved["scenario"],
        "geography_kind": resolved["geography_kind"],
        "runtime_versions": {"policyengine-us": "test-only"},
        "years": {str(year): {"status": "forecast"} for year in years},
        "geographies": [],
        "composition_method": "classified-inputs",
        "storage_method": "formula",
    }


def worker_result_fields(*, years, selection: dict | None = None) -> dict:
    """Return the SPM fields required on an economy worker result."""
    resolved = INSTALLED_SPM_SELECTION if selection is None else selection
    if resolved is None:
        return {}
    receipt = spm_receipt(years=years, selection=resolved)
    return {
        "spm_config": dict(resolved),
        "spm_provenance": {
            "baseline": [dict(receipt)],
            "reform": [dict(receipt)],
        },
    }


def household_result_fields(*, years, selection: dict | None = None) -> dict:
    """Return the SPM fields required on a household calculation result."""
    resolved = INSTALLED_SPM_SELECTION if selection is None else selection
    if resolved is None:
        return {}
    return {
        "spm_config": dict(resolved),
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

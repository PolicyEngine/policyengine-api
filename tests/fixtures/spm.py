"""Doubles for the canonical SPM boundary a certified bundle activates.

A certified bundle resolves an SPM selection for every US request. The API then
refuses to submit that request unless the selected worker advertises a matching
capability, and refuses to serve a result that carries no receipt for what was
measured. Doubles written while the pinned bundle was uncertified answer
neither, because the boundary was dormant and never asked them.

Every value here is read from the installed bundle manifest rather than written
down, so a double follows the pinned bundle instead of becoming a second copy
of it that the next bump would silently contradict. On a bundle whose US model
predates the canonical constructor the selection is `None`, the boundary stays
dormant, and every helper degrades to the legacy shapes.

Resolving the selection at import time also imports `policyengine_us` during
collection, before any test patches `datetime.datetime`, so the country import
inside the boundary is a `sys.modules` hit rather than a fresh import running
under a patched standard library.
"""

from __future__ import annotations

import pytest

from policyengine_api import spm
from policyengine_api.constants import POLICYENGINE_VERSION

# The contract identifier `worker_spm.validate_worker_spm` requires.
SPM_CONTRACT_VERSION = "canonical-spm-v1"

# What the installed bundle certifies for an unqualified US request, or None on
# a bundle whose model predates the contract.
INSTALLED_SPM_SELECTION = spm.normalize_spm_selection("us", None)


def worker_spm_capability(selection: dict | None = None) -> dict | None:
    """What a worker running this API's own bundle advertises to `/versions`."""
    resolved = INSTALLED_SPM_SELECTION if selection is None else selection
    if resolved is None:
        return None
    return {"contract_version": SPM_CONTRACT_VERSION, "defaults": dict(resolved)}


def worker_versions_document(
    *,
    bundle_version: str = POLICYENGINE_VERSION,
    app_name: str = "test-worker-app",
    country: str = "us",
    country_version: str | None = None,
    selection: dict | None = None,
) -> dict:
    """The gateway registry document `get_spm_capability` reads.

    Keyed by wrapper version, as the deployed registry is: the capability
    belongs to the bundle the worker runs, not to the country route that
    resolves to its application.
    """
    document: dict = {
        "policyengine": {bundle_version: app_name, "latest": bundle_version},
    }
    if country_version is not None:
        document[country] = {country_version: app_name, "latest": country_version}
    capability = worker_spm_capability(selection)
    if capability is not None:
        document["spm_capabilities"] = {bundle_version: capability}
    return document


def spm_receipt(*, years, selection: dict | None = None) -> dict:
    """One country provenance receipt covering the given calculation years."""
    resolved = INSTALLED_SPM_SELECTION if selection is None else selection
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


def spm_result_fields(*, years, selection: dict | None = None) -> dict:
    """The SPM half of a worker result, or nothing on an uncertified bundle."""
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


def household_receipt_fields(*, years, selection: dict | None = None) -> dict:
    """The SPM half of a cached household calculation.

    A household carries one receipt for the calculation it is, where a worker
    result carries a baseline and reform list for the comparison it ran.
    """
    resolved = INSTALLED_SPM_SELECTION if selection is None else selection
    if resolved is None:
        return {}
    return {
        "spm_config": dict(resolved),
        "spm_provenance": spm_receipt(years=years, selection=resolved),
    }


def country_calculate_kwargs(
    *, requested: bool = False, selection: dict | None = None
) -> dict:
    """The measurement arguments the service passes to a country package."""
    resolved = INSTALLED_SPM_SELECTION if selection is None else selection
    if resolved is None:
        return {}
    return {"spm": dict(resolved), "spm_requested": requested}


def spm_options(options: dict, selection: dict | None = None) -> dict:
    """Request options as the service resolves them against the bundle."""
    resolved = INSTALLED_SPM_SELECTION if selection is None else selection
    if resolved is None:
        return dict(options)
    return {**options, "spm": dict(resolved)}


def spm_options_hash_segment(selection: dict | None = None) -> str:
    """The segment a resolved selection contributes to a cache identity.

    Options are serialized in sorted-key order, so `spm` follows every option a
    caller sent. Derived rather than written out because the artifact hash it
    carries belongs to the pinned bundle.
    """
    resolved = INSTALLED_SPM_SELECTION if selection is None else selection
    return "" if resolved is None else f"&spm={resolved}"


@pytest.fixture
def legacy_bundle(monkeypatch):
    """Pin a bundle that predates the canonical SPM contract.

    Use this in tests that assert legacy behaviour by name: the resolution and
    the transport contract both differ on an uncertified bundle, so leaving the
    regime to whatever happens to be installed makes the assertion mean
    whichever thing the environment chose.
    """
    monkeypatch.setattr(spm, "_current_bundle", dict)
    monkeypatch.setattr(spm, "_installed_country_implements_spm", lambda _: False)
